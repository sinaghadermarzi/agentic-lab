"""shoplab.tools: calc safety, the 9 standard tools, run_tool robustness."""

import json

import pytest

from shoplab.tools import Ledger, Tool, calc, run_tool, standard_tools, to_openai_tools

EXPECTED_NAMES = {"get_order", "get_customer", "search_policy", "check_inventory",
                  "calc", "issue_refund", "create_replacement", "escalate", "finish"}


# --- calc --------------------------------------------------------------------

def test_calc_happy_paths():
    assert calc("2 + 3") == 5.0
    assert calc("2 * (3 + 4.5)") == 15.0
    assert calc("2**3") == 8.0
    assert calc("-4 + 1") == -3.0
    assert calc("7 / 2") == 3.5
    assert calc("0.9 * 189.99") == pytest.approx(170.991)
    assert isinstance(calc("1 + 1"), float)


@pytest.mark.parametrize("bad", [
    "x + 1",                      # names
    "__import__('os')",           # dunders / calls
    "abs(1)",                     # calls
    "1 < 2",                      # comparisons
    "'a' + 'b'",                  # strings
    "True",                       # bools are not numbers here
    "[1, 2]",                     # containers
    "1 if 2 else 3",              # conditionals
    "2 +",                        # syntax error
])
def test_calc_rejects_everything_but_arithmetic(bad):
    with pytest.raises(ValueError):
        calc(bad)


# --- standard_tools ----------------------------------------------------------

def test_standard_tools_is_the_nine_of_world_md():
    tools = standard_tools()
    assert set(tools) == EXPECTED_NAMES
    assert all(isinstance(t, Tool) for t in tools.values())
    risky = {name for name, t in tools.items() if t.risky}
    assert risky == {"issue_refund", "create_replacement"}


def test_tool_params_are_full_json_schemas():
    for t in standard_tools().values():
        assert t.params["type"] == "object"
        assert isinstance(t.params["properties"], dict)
        assert isinstance(t.params["required"], list)


def test_get_order_happy_and_unknown():
    tools = standard_tools()
    order = tools["get_order"].fn("ORD-7301")
    assert order["order_id"] == "ORD-7301"
    assert isinstance(order["items"], list)
    assert tools["get_order"].fn("ORD-9999") == {"error": "no such order ORD-9999"}


def test_get_customer_happy_and_unknown():
    tools = standard_tools()
    assert tools["get_customer"].fn("CUST-04")["customer_id"] == "CUST-04"
    assert tools["get_customer"].fn("CUST-99") == {"error": "no such customer CUST-99"}


def test_check_inventory_shape():
    tools = standard_tools()
    info = tools["check_inventory"].fn("LK-1001")
    assert info["sku"] == "LK-1001"
    assert isinstance(info["stock"], int) and isinstance(info["low_stock"], bool)
    assert "error" in tools["check_inventory"].fn("LK-9999")


def test_issue_refund_writes_ledger():
    ledger = Ledger()
    tools = standard_tools(ledger)
    result = tools["issue_refund"].fn("ORD-7301", 42.0, "damaged in transit")
    assert result["ok"] is True and result["refund_id"].startswith("REF-")
    assert len(ledger.entries) == 1
    entry = ledger.entries[0]
    assert entry["kind"] == "issue_refund"
    assert entry["order_id"] == "ORD-7301" and entry["amount_usd"] == 42.0
    # unknown order: error dict, nothing recorded
    assert tools["issue_refund"].fn("ORD-9999", 1.0, "x") == {
        "error": "no such order ORD-9999"}
    assert len(ledger.entries) == 1


def test_create_replacement_writes_ledger_and_checks_the_order_line():
    ledger = Ledger()
    tools = standard_tools(ledger)
    order = tools["get_order"].fn("ORD-7301")
    on_order = order["items"][0]["sku"]
    off_order = next(s for s in ("LK-1001", "LK-1002", "LK-1003")
                     if all(i["sku"] != s for i in order["items"]))
    result = tools["create_replacement"].fn("ORD-7301", on_order)
    assert result["ok"] is True and result["replacement_id"].startswith("REP-")
    assert ledger.entries[0]["kind"] == "create_replacement"
    assert "error" in tools["create_replacement"].fn("ORD-7301", off_order)
    assert "error" in tools["create_replacement"].fn("ORD-9999", on_order)
    assert len(ledger.entries) == 1


def test_finish_returns_its_args_dict():
    tools = standard_tools()
    assert tools["finish"].fn("deny", "pol-returns", None) == {
        "decision": "deny", "policy_id": "pol-returns", "refund_usd": None}
    assert tools["finish"].fn("approve_refund", "pol-damaged", 42.45) == {
        "decision": "approve_refund", "policy_id": "pol-damaged", "refund_usd": 42.45}


def test_ledger_record_returns_the_entry():
    ledger = Ledger()
    entry = ledger.record("test_kind", a=1)
    assert entry == {"kind": "test_kind", "a": 1}
    assert ledger.entries == [entry]


# --- run_tool never raises ---------------------------------------------------

def test_run_tool_happy_path_is_json():
    tools = standard_tools()
    result = json.loads(run_tool(tools, "calc", {"expr": "2 + 2"}))
    assert result == 4.0


def test_run_tool_unknown_tool():
    result = json.loads(run_tool(standard_tools(), "launch_rocket", {}))
    assert "error" in result and "launch_rocket" in result["error"]


def test_run_tool_wrong_args():
    result = json.loads(run_tool(standard_tools(), "get_order", {"nope": 1}))
    assert "error" in result


def test_run_tool_fn_exception():
    result = json.loads(run_tool(standard_tools(), "calc", {"expr": "__import__('os')"}))
    assert "error" in result


def test_run_tool_missing_required_arg():
    result = json.loads(run_tool(standard_tools(), "issue_refund", {"order_id": "ORD-7301"}))
    assert "error" in result


# --- to_openai_tools ---------------------------------------------------------

def test_to_openai_tools_shape():
    tools = standard_tools()
    wire = to_openai_tools(tools)
    assert len(wire) == 9
    for item in wire:
        assert item["type"] == "function"
        fn = item["function"]
        assert set(fn) == {"name", "description", "parameters"}
        assert fn["parameters"] is tools[fn["name"]].params
