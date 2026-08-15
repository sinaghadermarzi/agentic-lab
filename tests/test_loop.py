"""shoplab.loop.run_agent against a scripted FakeLLM -- no network anywhere."""

import json

import shoplab.llm
from fakes import make_text_msg, make_tool_call_msg
from shoplab.loop import run_agent
from shoplab.tools import Tool


class FakeLLM:
    """Returns the scripted responses in order; records every call it gets."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, messages, **kw):
        self.calls.append({"messages": list(messages), "kw": kw})
        return self.script.pop(0)


def make_tools(executed):
    """A tiny toolset whose fns log to `executed` so tests can see what ran."""
    def get_order(order_id):
        executed.append(("get_order", order_id))
        return {"order_id": order_id, "status": "delivered", "total_usd": 301.50}

    def issue_refund(order_id, amount_usd, reason):
        executed.append(("issue_refund", order_id))
        return {"ok": True, "refund_id": "REF-1001"}

    def finish(decision, policy_id, refund_usd=None):
        executed.append(("finish", decision))
        return {"decision": decision, "policy_id": policy_id, "refund_usd": refund_usd}

    schema = {"type": "object", "properties": {}, "required": []}
    return {
        "get_order": Tool("get_order", "look up an order", schema, get_order),
        "issue_refund": Tool("issue_refund", "send money", schema, issue_refund,
                             risky=True),
        "finish": Tool("finish", "final answer", schema, finish),
    }


def install(monkeypatch, script):
    fake = FakeLLM(script)
    monkeypatch.setattr(shoplab.llm, "complete", fake)
    return fake


# --- (1) tool call then finish -----------------------------------------------

def test_tool_call_then_finish(monkeypatch):
    finish_args = {"decision": "approve_refund", "policy_id": "pol-returns",
                   "refund_usd": 301.50}
    fake = install(monkeypatch, [
        make_tool_call_msg("get_order", {"order_id": "ORD-7301"}),
        make_tool_call_msg("finish", finish_args),
    ])
    executed = []
    result = run_agent("triage ORD-7301", make_tools(executed))
    assert result.stop_reason == "finish"
    assert result.answer == finish_args
    assert result.steps == 2
    assert executed[0] == ("get_order", "ORD-7301")
    # messages: user, assistant, tool, assistant, tool -- tool result in between
    assert result.messages[0]["role"] == "user"
    tool_msg = result.messages[2]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call-1"
    assert json.loads(tool_msg["content"])["order_id"] == "ORD-7301"
    # every model call carried the tools in wire format
    assert all(c["kw"]["tools"][0]["type"] == "function" for c in fake.calls)


def test_system_prompt_goes_first(monkeypatch):
    fake = install(monkeypatch, [make_text_msg("ok")])
    result = run_agent("hi", make_tools([]), system="you are the ops desk")
    assert result.messages[0] == {"role": "system", "content": "you are the ops desk"}
    assert result.messages[1] == {"role": "user", "content": "hi"}


# --- (2) plain text answer ---------------------------------------------------

def test_plain_text_stops_the_loop(monkeypatch):
    install(monkeypatch, [make_text_msg("The order was delivered on June 19.")])
    result = run_agent("when was ORD-7301 delivered?", make_tools([]))
    assert result.stop_reason == "text"
    assert result.answer == "The order was delivered on June 19."
    assert result.steps == 1


# --- (3) never finishing -----------------------------------------------------

def test_max_steps(monkeypatch):
    script = [make_tool_call_msg("get_order", {"order_id": "ORD-7301"})
              for _ in range(3)]
    fake = install(monkeypatch, script)
    result = run_agent("loop forever", make_tools([]), max_steps=3)
    assert result.stop_reason == "max_steps"
    assert result.answer is None
    assert result.steps == 3
    assert len(fake.calls) == 3


# --- (4) before_tool veto ----------------------------------------------------

def test_before_tool_veto_blocks_risky_fn(monkeypatch):
    install(monkeypatch, [
        make_tool_call_msg("issue_refund",
                           {"order_id": "ORD-7301", "amount_usd": 999.0,
                            "reason": "model got tricked"}),
        make_text_msg("I could not issue the refund."),
    ])
    executed = []
    tools = make_tools(executed)
    vetoes = []

    def before_tool(name, args):
        vetoes.append(name)
        return not tools[name].risky

    result = run_agent("refund everything", tools, before_tool=before_tool)
    tool_msg = result.messages[2]
    assert tool_msg["role"] == "tool"
    assert "blocked by policy" in tool_msg["content"]
    assert executed == []            # the risky fn never ran
    assert vetoes == ["issue_refund"]
    assert result.stop_reason == "text"


def test_before_tool_true_lets_the_call_through(monkeypatch):
    install(monkeypatch, [
        make_tool_call_msg("get_order", {"order_id": "ORD-7301"}),
        make_text_msg("done"),
    ])
    executed = []
    result = run_agent("look it up", make_tools(executed),
                       before_tool=lambda name, args: True)
    assert executed == [("get_order", "ORD-7301")]
    assert result.stop_reason == "text"


# --- (5) malformed arguments JSON --------------------------------------------

def test_malformed_arguments_become_error_and_loop_continues(monkeypatch):
    install(monkeypatch, [
        make_tool_call_msg("get_order", '{"order_id": "ORD-7301'),  # broken JSON
        make_text_msg("sorry, retrying"),
    ])
    executed = []
    result = run_agent("triage", make_tools(executed))
    tool_msg = result.messages[2]
    assert tool_msg["role"] == "tool"
    assert "error" in json.loads(tool_msg["content"])
    assert executed == []            # nothing ran with broken args
    assert result.stop_reason == "text" and result.steps == 2


# --- extras: truncation and the on_step hook ---------------------------------

def test_tool_result_truncated_to_max_result_chars(monkeypatch):
    install(monkeypatch, [
        make_tool_call_msg("get_order", {"order_id": "ORD-7301"}),
        make_text_msg("done"),
    ])
    result = run_agent("look it up", make_tools([]), max_result_chars=10)
    assert len(result.messages[2]["content"]) == 10


def test_on_step_hook_sees_every_message(monkeypatch):
    install(monkeypatch, [
        make_tool_call_msg("get_order", {"order_id": "ORD-7301"}),
        make_text_msg("done"),
    ])
    seen = []
    run_agent("look it up", make_tools([]),
              on_step=lambda step, msg: seen.append(step))
    assert seen == [1, 2]
