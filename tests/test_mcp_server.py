"""The chapter-13 MCP server registers the expected tools/resource/prompt.

Pure offline introspection: importing ``mcp_servers.shopdesk_server`` builds the
``FastMCP`` instance (the ``if __name__ == "__main__"`` guard means no
``mcp.run()`` fires on import), and we read its managers directly. No stdio
subprocess, no event loop -- the live end-to-end round-trip is exercised by the
chapter-13 client, not here.
"""

import sys
from pathlib import Path

# mcp_servers/ lives at the repo root (a namespace package), next to src/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("mcp", reason="needs the .[mcp] extra (mcp>=1.28,<2)")

from mcp_servers import shopdesk_server as srv

MCP = srv.mcp

EXPECTED_TOOLS = {
    "get_order", "get_customer", "search_policy", "check_inventory",
    "refund_preview",
}


def test_import_does_not_start_a_server():
    # A FastMCP instance exists and is named; importing did not block on serve().
    assert MCP.name == "larkspur-shopdesk"
    assert MCP.instructions and "ops desk" in MCP.instructions


def test_expected_tools_registered():
    names = {t.name for t in MCP._tool_manager.list_tools()}
    assert names == EXPECTED_TOOLS


def test_read_tools_wrap_shoplab_and_have_schemas():
    tools = {t.name: t for t in MCP._tool_manager.list_tools()}
    # get_order takes an order_id string (schema inferred from the type hint).
    schema = tools["get_order"].parameters
    assert schema["type"] == "object"
    assert "order_id" in schema["properties"]
    # search_policy exposes the optional k with a default (not required).
    sp = tools["search_policy"].parameters
    assert "query" in sp["properties"] and "k" in sp["properties"]
    assert sp.get("required", []) == ["query"]


def test_iserror_demo_tool_present():
    # refund_preview is the tool that RAISES -> isError result path in ch13.
    tools = {t.name: t for t in MCP._tool_manager.list_tools()}
    assert "refund_preview" in tools
    params = tools["refund_preview"].parameters["properties"]
    assert {"order_id", "amount_usd"} <= set(params)


def test_policy_resource_template_registered():
    templates = MCP._resource_manager.list_templates()
    uris = {t.uri_template for t in templates}
    assert "policy://{policy_id}" in uris
    # It is a template (parameterised), so it is NOT a concrete resource.
    assert MCP._resource_manager.list_resources() == []


def test_triage_prompt_registered():
    prompts = {p.name: p for p in MCP._prompt_manager.list_prompts()}
    assert "triage_ticket" in prompts
    arg_names = {a.name for a in prompts["triage_ticket"].arguments}
    assert arg_names == {"order_id", "reason"}
