"""Larkspur ops desk, exposed over the Model Context Protocol (stdio).

This is the server chapter 13 speaks to. It wraps the same micro-world the
rest of the course uses (``shoplab.world`` loaders and ``shoplab.tools``) and
re-publishes it through the three MCP primitives so a client can discover and
call them over a stdio transport:

- **Tools** (functions the model may call): ``get_order``, ``get_customer``,
  ``search_policy``, ``check_inventory`` -- thin wrappers over the existing
  shoplab logic, plus ``refund_preview`` which deliberately *raises* to show
  the ``isError`` result path.
- **Resource** (context the client may read): ``policy://{policy_id}`` -- a
  policy document by id, a parameterised resource *template*.
- **Prompt** (a reusable message template): ``triage_ticket`` -- the ops-desk
  triage instructions, parameterised by order and reason.

Why FastMCP from ``mcp`` 1.x and not 2.x: ``pip install mcp`` now pulls the
reworked 2.x line, which renamed the high-level server class from ``FastMCP``
to ``MCPServer``; the MCP Python SDK README itself advises pinning ``mcp<2``
(``mcp>=1.28,<2``) until you migrate, and the agent ecosystem the course
touches (arize-phoenix, agent-framework-core, crewai, strands-agents) all pin
``mcp<2`` too. See docs/citations.json and chapter 13.

Run it directly for a stdio server:  python mcp_servers/shopdesk_server.py
The data directory is found by ``shoplab.world`` relative to the installed
package, so this works unchanged when a notebook launches it as a subprocess
from any working directory (no SHOPLAB_DATA needed).
"""

from mcp.server.fastmcp import FastMCP

from shoplab import world
from shoplab.tools import standard_tools

# Build the world-backed toolset once. ``standard_tools`` reads the data files
# through ``shoplab.world`` (which resolves data/ relative to the installed
# package), so importing this module works from any cwd -- including as a
# subprocess spawned by an nbclient-run notebook.
_STD = standard_tools()

mcp = FastMCP(
    "larkspur-shopdesk",
    instructions=(
        "The Larkspur Outfitters ops desk over MCP. Use the tools to look up "
        "orders, customers, stock, and store policy; read policy://{id} for a "
        "full policy document; load the triage_ticket prompt to triage a "
        "return/refund ticket."
    ),
)


# --- Tools -----------------------------------------------------------------
# Thin wrappers over shoplab. FastMCP builds each tool's input schema from the
# type hints, so the annotations below are load-bearing.

@mcp.tool()
def get_order(order_id: str) -> dict:
    """Look up a Larkspur order by id: items, totals, status, dates.

    Returns ``{"error": ...}`` for an unknown id -- an ordinary (non-isError)
    result the model can read and recover from.
    """
    return _STD["get_order"].fn(order_id)


@mcp.tool()
def get_customer(customer_id: str) -> dict:
    """Look up a customer by id: tier, loyalty flags, lifetime spend."""
    return _STD["get_customer"].fn(customer_id)


@mcp.tool()
def search_policy(query: str, k: int = 2) -> list[dict]:
    """Keyword-search the 12 store policy documents; returns the top ``k``."""
    return world.search_policy(query, k)


@mcp.tool()
def check_inventory(sku: str) -> dict:
    """Stock level and reorder status for a sku (e.g. LK-1001)."""
    return _STD["check_inventory"].fn(sku)


@mcp.tool()
def refund_preview(order_id: str, amount_usd: float) -> dict:
    """Preview a refund against an order without committing it.

    isError demo: a *tool-execution* error. If the order is unknown or the
    amount exceeds the order total this raises, and FastMCP reports it inside
    the tool result with ``isError: true`` (the model sees the message and can
    recover) -- it is NOT a protocol-level JSON-RPC error.
    """
    order = _STD["get_order"].fn(order_id)
    if "error" in order:
        raise ValueError(order["error"])
    total = order["total_usd"]
    if amount_usd > total:
        raise ValueError(
            f"refund {amount_usd:.2f} exceeds order total {total:.2f}")
    return {"order_id": order_id, "amount_usd": round(amount_usd, 2),
            "order_total_usd": total, "within_total": True}


# --- Resource --------------------------------------------------------------
# A parameterised resource *template*: the {policy_id} placeholder makes this a
# template (it appears under list_resource_templates, not list_resources), and
# the client reads a concrete instance with read_resource("policy://pol-...").

@mcp.resource("policy://{policy_id}", name="policy_document",
              description="A Larkspur store policy document, by id.",
              mime_type="text/plain")
def policy_document(policy_id: str) -> str:
    """Return the full text of one store policy (e.g. policy://pol-returns).

    Reading an unknown id raises, which the protocol surfaces to the client as
    a JSON-RPC error (contrast with the refund_preview isError path).
    """
    for p in world.load_policies():
        if p["id"] == policy_id:
            return f"{p['title']}\n\n{p['text']}"
    raise ValueError(f"no such policy {policy_id}")


# --- Prompt ----------------------------------------------------------------
# A reusable message template. Its parameters become the prompt's arguments;
# the returned string is delivered to the client as a single user message.

@mcp.prompt(title="Triage a return ticket")
def triage_ticket(order_id: str, reason: str) -> str:
    """Ops-desk triage instructions for one return/refund ticket."""
    return (
        "You are the Larkspur Outfitters ops desk. Triage this return/refund "
        "request and decide what the customer gets.\n\n"
        f"Order: {order_id}\n"
        f"Customer's stated reason: {reason}\n\n"
        "Steps: call get_order to see the order and customer, get_customer for "
        "their tier and loyalty flags, and search_policy on the reason to find "
        "the governing policy; read policy://{id} for the full text. Then state "
        "the decision (approve_refund | partial_refund | replacement | "
        "store_credit | deny | escalate), cite the policy id, and give the "
        "dollar amount moved (or null)."
    )


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
