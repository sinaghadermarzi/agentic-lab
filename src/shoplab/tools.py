"""The ops-desk toolset: ``Tool``, ``Ledger``, ``calc``, and the 9 standard tools.

Chapter 02 builds this module. ``standard_tools`` returns the toolset of
docs/WORLD.md backed by ``shoplab.world``; the two risky tools write to an
in-memory ``Ledger`` (the object of the approval gates in chapter 08 and the
injection defenses in chapter 09). ``run_tool`` is the agent loop's only entry
point into a tool: it always returns a JSON string and never raises, so a bad
call becomes a tool message the model can read and recover from.
"""

import ast
import json
import operator
from dataclasses import dataclass
from typing import Callable

from shoplab import world


@dataclass
class Tool:
    """One callable the agent may use. ``params`` is a full JSON schema dict:
    ``{"type": "object", "properties": {...}, "required": [...]}``."""
    name: str
    description: str
    params: dict
    fn: Callable
    risky: bool = False


class Ledger:
    """In-memory record of side effects (refunds, replacements)."""

    def __init__(self):
        self.entries: list[dict] = []

    def record(self, kind: str, **fields) -> dict:
        entry = {"kind": kind, **fields}
        self.entries.append(entry)
        return entry


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow}


def calc(expr: str) -> float:
    """Evaluate plain arithmetic by walking the AST -- never ``eval``.

    Allowed: int/float literals, ``+ - * / **``, unary minus, parentheses.
    Anything else (names, calls, comparisons, ...) raises ValueError.
    """
    def walk(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        raise ValueError("calc only does arithmetic")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        raise ValueError("calc only does arithmetic") from None
    return float(walk(tree.body))


def _schema(props: dict, required: list) -> dict:
    return {"type": "object", "properties": props, "required": required}


def standard_tools(ledger=None) -> dict[str, Tool]:
    """The 9 standard tools of docs/WORLD.md, backed by the world data.

    Index dicts are built once per call, so a fresh toolset sees fresh data.
    ``issue_refund`` and ``create_replacement`` (the risky pair) append to
    ``ledger`` -- pass your own to observe what the agent did.
    """
    ledger = ledger if ledger is not None else Ledger()
    orders = {o["order_id"]: o for o in world.load_orders()}
    customers = {c["customer_id"]: c for c in world.load_customers()}
    products = {p["sku"]: p for p in world.load_products()}

    def get_order(order_id):
        return orders.get(order_id, {"error": f"no such order {order_id}"})

    def get_customer(customer_id):
        return customers.get(customer_id, {"error": f"no such customer {customer_id}"})

    def check_inventory(sku):
        p = products.get(sku)
        if p is None:
            return {"error": f"no such sku {sku}"}
        return {"sku": p["sku"], "name": p["name"], "stock": p["stock"],
                "reorder_threshold": p["reorder_threshold"],
                "low_stock": p["stock"] <= p["reorder_threshold"]}

    def issue_refund(order_id, amount_usd, reason):
        if order_id not in orders:
            return {"error": f"no such order {order_id}"}
        refund_id = f"REF-{1001 + len(ledger.entries)}"
        ledger.record("issue_refund", refund_id=refund_id, order_id=order_id,
                      amount_usd=amount_usd, reason=reason)
        return {"ok": True, "refund_id": refund_id}

    def create_replacement(order_id, sku):
        order = orders.get(order_id)
        if order is None:
            return {"error": f"no such order {order_id}"}
        if not any(item["sku"] == sku for item in order["items"]):
            return {"error": f"sku {sku} is not on order {order_id}"}
        replacement_id = f"REP-{1001 + len(ledger.entries)}"
        ledger.record("create_replacement", replacement_id=replacement_id,
                      order_id=order_id, sku=sku)
        return {"ok": True, "replacement_id": replacement_id}

    def escalate(ticket_id, note):
        return {"ok": True, "ticket_id": ticket_id, "note": note,
                "queued_for": "human review"}

    def finish(decision, policy_id, refund_usd=None):
        return {"decision": decision, "policy_id": policy_id, "refund_usd": refund_usd}

    tools = [
        Tool("get_order", "Look up an order by id: items, totals, status, dates.",
             _schema({"order_id": {"type": "string", "description": "e.g. ORD-7301"}},
                     ["order_id"]), get_order),
        Tool("get_customer", "Look up a customer by id: tier, flags, history.",
             _schema({"customer_id": {"type": "string", "description": "e.g. CUST-04"}},
                     ["customer_id"]), get_customer),
        Tool("search_policy", "Keyword-search the 12 store policy documents.",
             _schema({"query": {"type": "string"},
                      "k": {"type": "integer",
                            "description": "how many docs to return (default 2)"}},
                     ["query"]), world.search_policy),
        Tool("check_inventory", "Stock level and reorder status for a sku.",
             _schema({"sku": {"type": "string", "description": "e.g. LK-1001"}},
                     ["sku"]), check_inventory),
        Tool("calc", "Evaluate an arithmetic expression, e.g. '0.9 * 189.99'.",
             _schema({"expr": {"type": "string"}}, ["expr"]), calc),
        Tool("issue_refund", "Send money back to the customer. Irreversible.",
             _schema({"order_id": {"type": "string"},
                      "amount_usd": {"type": "number"},
                      "reason": {"type": "string"}},
                     ["order_id", "amount_usd", "reason"]), issue_refund, risky=True),
        Tool("create_replacement", "Ship a replacement unit of an ordered sku. Irreversible.",
             _schema({"order_id": {"type": "string"}, "sku": {"type": "string"}},
                     ["order_id", "sku"]), create_replacement, risky=True),
        Tool("escalate", "Hand the ticket to a human reviewer with a note.",
             _schema({"ticket_id": {"type": "string"}, "note": {"type": "string"}},
                     ["ticket_id", "note"]), escalate),
        Tool("finish", "Give your final ticket decision and stop.",
             _schema({"decision": {"type": "string",
                                   "enum": ["approve_refund", "partial_refund",
                                            "replacement", "store_credit", "deny",
                                            "escalate"]},
                      "policy_id": {"type": "string", "description": "e.g. pol-returns"},
                      # a ["number","null"] union type here makes some providers
                      # truncate the call mid-arguments; keep the schema plain and
                      # let refund_usd default to None when the model omits it
                      "refund_usd": {"type": "number",
                                     "description": "dollars moved; omit if none"}},
                     ["decision", "policy_id"]), finish),
    ]
    return {t.name: t for t in tools}


def run_tool(tools: dict, name: str, args: dict) -> str:
    """Execute one tool call. Always returns a JSON string; never raises."""
    if name not in tools:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        return json.dumps(tools[name].fn(**args))
    except Exception as exc:  # wrong args, fn bugs, unserializable results
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"[:200]})


def to_openai_tools(tools: dict) -> list:
    """The OpenAI function-calling wire format that litellm expects."""
    return [{"type": "function",
             "function": {"name": t.name, "description": t.description,
                          "parameters": t.params}}
            for t in tools.values()]
