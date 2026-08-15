"""shoplab.rules.decide: golden cases from real data, boundaries, and a property."""

import copy

import pytest

from shoplab import world
from shoplab.rules import decide

TICKETS = world.load_tickets()
ALL_TICKETS = TICKETS["train"] + TICKETS["dev"] + TICKETS["test"]
TICKET_BY_ID = {t["ticket_id"]: t for t in ALL_TICKETS}
ORDER_BY_ID = {o["order_id"]: o for o in world.load_orders()}
CUSTOMER_BY_ID = {c["customer_id"]: c for c in world.load_customers()}


def run(ticket):
    return decide(ticket, ORDER_BY_ID[ticket["order_id"]],
                  CUSTOMER_BY_ID[ticket["customer_id"]])


def real(ticket_id):
    """A deep copy of a real ticket row, safe to mutate in boundary tests."""
    return copy.deepcopy(TICKET_BY_ID[ticket_id])


# --- one golden case per decision type (real rows) ---------------------------

def test_golden_approve_refund_damaged_with_shipping():
    # TKT-2201: damaged in transit, $36.50 item under the photo threshold,
    # 5 days since delivery -> item price plus full shipping back.
    assert run(real("TKT-2201")) == {
        "decision": "approve_refund", "policy_id": "pol-damaged", "refund_usd": 42.45}


def test_golden_partial_refund_opened_non_vip():
    # TKT-2205 (the fixed appendix scenario): opened boots, member tier,
    # in-window -> 90% of 189.99 = 170.99 after the cent rounding.
    assert run(real("TKT-2205")) == {
        "decision": "partial_refund", "policy_id": "pol-restocking", "refund_usd": 170.99}


def test_golden_replacement_size_swap():
    # TKT-2204: unopened gloves, wrong size, wants a swap -> exchange, no money moves.
    assert run(real("TKT-2204")) == {
        "decision": "replacement", "policy_id": "pol-exchanges", "refund_usd": None}


def test_golden_store_credit_full_value():
    # TKT-2207: unopened socks, store credit requested -> full item value as credit.
    assert run(real("TKT-2207")) == {
        "decision": "store_credit", "policy_id": "pol-store-credit", "refund_usd": 22.0}


def test_golden_deny_out_of_window():
    # TKT-2212: change of mind at day 32 -> past the 30-day window, denied.
    assert run(real("TKT-2212")) == {
        "decision": "deny", "policy_id": "pol-returns", "refund_usd": None}


def test_golden_escalate_serial_returner():
    # TKT-2206: CUST-12 is a flagged serial returner -> straight to fraud review,
    # even with a photo and a defective item.
    assert run(real("TKT-2206")) == {
        "decision": "escalate", "policy_id": "pol-fraud", "refund_usd": None}


# --- boundary behavior -------------------------------------------------------

def test_day_30_is_inside_the_window():
    ticket = real("TKT-2215")  # unopened refund request, standard tier
    ticket["days_since_delivery"] = 30
    assert run(ticket) == {
        "decision": "approve_refund", "policy_id": "pol-returns", "refund_usd": 29.0}


def test_day_31_is_denied():
    ticket = real("TKT-2215")
    ticket["days_since_delivery"] = 31
    assert run(ticket) == {
        "decision": "deny", "policy_id": "pol-returns", "refund_usd": None}


def test_vip_opened_gets_full_refund():
    # TKT-2202: CUST-01 is vip, item opened -> restocking fee waived, full $219.
    assert CUSTOMER_BY_ID["CUST-01"]["tier"] == "vip"
    assert run(real("TKT-2202")) == {
        "decision": "approve_refund", "policy_id": "pol-restocking", "refund_usd": 219.0}


def test_photo_threshold_is_strictly_over_75():
    # A damaged claim of exactly $75 with no photo is NOT held for evidence:
    # the threshold is "over $75", so it approves with shipping refunded.
    ticket = real("TKT-2201")
    order = copy.deepcopy(ORDER_BY_ID[ticket["order_id"]])
    line = next(i for i in order["items"] if i["sku"] == ticket["sku"])
    line["unit_price_usd"] = 75.0
    result = decide(ticket, order, CUSTOMER_BY_ID[ticket["customer_id"]])
    assert result == {"decision": "approve_refund", "policy_id": "pol-damaged",
                      "refund_usd": round(75.0 + order["shipping_usd"], 2)}


def test_unevidenced_damage_over_300_escalates():
    # TKT-2209: $319 damaged claim, no photo -> fraud review, not a plain deny.
    assert run(real("TKT-2209")) == {
        "decision": "escalate", "policy_id": "pol-fraud", "refund_usd": None}


def test_unevidenced_damage_at_exactly_300_denies_not_escalates():
    ticket = real("TKT-2209")
    order = copy.deepcopy(ORDER_BY_ID[ticket["order_id"]])
    line = next(i for i in order["items"] if i["sku"] == ticket["sku"])
    line["unit_price_usd"] = 300.0
    result = decide(ticket, order, CUSTOMER_BY_ID[ticket["customer_id"]])
    assert result == {"decision": "deny", "policy_id": "pol-damaged", "refund_usd": None}


def test_sku_not_in_order_raises_value_error():
    ticket = real("TKT-2201")
    ticket["sku"] = "LK-9999"
    with pytest.raises(ValueError):
        run(ticket)


# --- property over all 40 real tickets ---------------------------------------

def test_all_tickets_decide_matches_gold_and_refund_is_bounded():
    for ticket in ALL_TICKETS:
        order = ORDER_BY_ID[ticket["order_id"]]
        result = run(ticket)
        assert result == ticket["gold"], ticket["ticket_id"]
        refund = result["refund_usd"]
        assert refund is None or (
            0 < refund <= order["total_usd"] + order["shipping_usd"]
        ), f"{ticket['ticket_id']}: refund {refund} out of bounds"
