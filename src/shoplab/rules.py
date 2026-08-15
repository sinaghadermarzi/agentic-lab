"""Deterministic refund rules for the Larkspur ops desk.

This module is the spec the agent is graded against: the gold labels in
``data/tickets.json`` are computed by ``decide``, and chapter 04 teaches this
cascade branch by branch before scoring the agent against it. It mirrors the
normative cascade in ``docs/WORLD.md`` exactly - first match wins, and every
branch cites the policy document it comes from.
"""

RETURN_WINDOW_DAYS = 30    # pol-returns
WARRANTY_DAYS = 365        # pol-defective
RESTOCKING_FEE = 0.10      # pol-restocking (waived for vip: pol-loyalty)
PHOTO_THRESHOLD_USD = 75   # pol-damaged
ESCALATE_VALUE_USD = 300   # pol-fraud


# >>> shoplab.rules.decide
def decide(ticket: dict, order: dict, customer: dict) -> dict:
    """Apply the 9-step first-match-wins cascade from docs/WORLD.md."""
    line = next((i for i in order["items"] if i["sku"] == ticket["sku"]), None)
    if line is None:
        raise ValueError(
            f"sku {ticket['sku']!r} is not an item of order {order['order_id']!r}"
        )
    item_value = round(ticket["qty"] * line["unit_price_usd"], 2)

    condition = ticket["item_condition"]
    action = ticket["requested_action"]
    days = ticket["days_since_delivery"]

    def result(decision, policy_id, refund_usd):
        return {"decision": decision, "policy_id": policy_id, "refund_usd": refund_usd}

    # 1. Flagged serial returners always go to a human. (pol-fraud)
    if customer["serial_returner"]:
        return result("escalate", "pol-fraud", None)

    # 2. Damage/defect claims over $75 need a photo; big unevidenced claims
    #    escalate, the rest are denied. (pol-fraud / pol-damaged)
    if (condition in ("damaged", "defective")
            and item_value > PHOTO_THRESHOLD_USD
            and not ticket["evidence_photo"]):
        if item_value > ESCALATE_VALUE_USD:
            return result("escalate", "pol-fraud", None)
        return result("deny", "pol-damaged", None)

    # 3. Damaged in transit: item price plus full original shipping, inside
    #    the return window. (pol-damaged / pol-returns)
    if condition == "damaged":
        if days <= RETURN_WINDOW_DAYS:
            return result("approve_refund", "pol-damaged",
                          round(item_value + order["shipping_usd"], 2))
        return result("deny", "pol-returns", None)

    # 4. Defective: 365-day warranty, replacement or refund. (pol-defective)
    if condition == "defective":
        if days <= WARRANTY_DAYS:
            if action == "replacement":
                return result("replacement", "pol-defective", None)
            return result("approve_refund", "pol-defective", item_value)
        return result("deny", "pol-defective", None)

    # 5. Change-of-mind requests past the return window. (pol-returns)
    if days > RETURN_WINDOW_DAYS:
        return result("deny", "pol-returns", None)

    # 6. Replacement for a non-defective item. (pol-exchanges)
    if action == "replacement":
        return result("replacement", "pol-exchanges", None)

    # 7. Store credit: full item value, restocking fee waived. (pol-store-credit)
    if action == "store_credit":
        return result("store_credit", "pol-store-credit", item_value)

    # Only requested_action == "refund" reaches this point.
    # 8. Unopened refund: full item value. (pol-returns)
    if condition == "unopened":
        return result("approve_refund", "pol-returns", item_value)

    # 9. Opened refund: 10% restocking fee, waived for vip. (pol-restocking)
    if customer["tier"] == "vip":
        return result("approve_refund", "pol-restocking", item_value)
    return result("partial_refund", "pol-restocking",
                  round(item_value * (1 - RESTOCKING_FEE), 2))
# <<< shoplab.rules.decide
