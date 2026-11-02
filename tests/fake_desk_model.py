"""A scripted, conversation-driven stand-in for litellm.completion (chapter 19 e2e).

Patched over litellm.completion, it lets shoplab.llm.complete run for real (the
LEDGER row, the bridge, pi on the far side) with no network and no key. Each
call reads the conversation since the last user message and plays the next
move of a competent desk agent: look up order + customer (one parallel turn),
search policy, do the arithmetic, attempt the refund only if the task asks for
it, then finish. Deterministic.
"""

import json
import re
from types import SimpleNamespace

CALLS = []


def _tc(i, name, args, turn):
    return SimpleNamespace(id=f"call_{turn}_{i}", type="function",
                           function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _resp(content=None, calls=None, finish="stop"):
    msg = SimpleNamespace(role="assistant", content=content, tool_calls=calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)],
                           usage=SimpleNamespace(prompt_tokens=900, completion_tokens=40),
                           _hidden_params={"response_cost": 0.0})


def fake_completion(*, model, messages, tools=None, **kw):
    CALLS.append({"model": model, "n_messages": len(messages),
                  "tools": [t["function"]["name"] for t in tools or []], "kw": sorted(kw)})
    names = {t["function"]["name"] for t in tools or []}
    last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
    task = messages[last_user]["content"] or ""
    done = [tc["function"]["name"] for m in messages[last_user:] if m["role"] == "assistant"
            for tc in m.get("tool_calls") or []]
    turn = len(CALLS)
    if not names or task.startswith("Which decision"):        # the resumed follow-up
        history = json.dumps(messages)
        answer = ("partial_refund under pol-restocking, refund 170.99"
                  if "partial_refund" in history else "no decision found in the history")
        return _resp(f"I decided {answer}.")
    order = (re.findall(r"ORD-\d+", task) or ["ORD-7312"])[0]
    customer = (re.findall(r"CUST-\d+", task) or ["CUST-07"])[0]
    if names == {"get_order"}:                                   # 01-stream: one tool, one call
        if "get_order" not in done:
            return _resp(None, [_tc(0, "get_order", {"order_id": order}, turn)], "tool_calls")
        return _resp("Order ORD-7312 cost 189.99 dollars.")
    if "get_order" not in done:
        return _resp("Looking up the order and the customer.",
                     [_tc(0, "get_order", {"order_id": order}, turn),
                      _tc(1, "get_customer", {"customer_id": customer}, turn)], "tool_calls")
    if "search_policy" not in done:
        return _resp(None, [_tc(0, "search_policy", {"query": "opened item restocking fee"}, turn)],
                     "tool_calls")
    if "calc" not in done:
        return _resp(None, [_tc(0, "calc", {"expr": "0.9 * 189.99"}, turn)], "tool_calls")
    wants_refund = bool(re.search(r"issue the refund|carry out your decision", task))
    if wants_refund and "issue_refund" in names and "issue_refund" not in done:
        return _resp(None, [_tc(0, "issue_refund", {"order_id": order, "amount_usd": 170.99,
                                                     "reason": "opened return, 10% restocking"},
                                turn)], "tool_calls")
    return _resp(None, [_tc(0, "finish", {"decision": "partial_refund",
                                          "policy_id": "pol-restocking", "refund_usd": 170.99},
                            turn)], "tool_calls")
