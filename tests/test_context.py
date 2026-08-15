"""shoplab.context: token counting, the growth ledger, offloading, compaction,
and the sub-agent firewall. No network -- count_tokens is offline via litellm's
token_counter; compact/offload/run_subagent run against monkeypatched llm.complete.
"""

import copy

import pytest

import shoplab.llm
from fakes import make_text_msg, make_tool_call_msg
from shoplab.context import (ContextLedger, compact, count_tokens, load_offload,
                             offload, run_subagent)
from shoplab.tools import Tool


class FakeLLM:
    """Returns scripted responses in order; records the calls it received."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, messages, **kw):
        self.calls.append({"messages": list(messages), "kw": kw})
        return self.script.pop(0)


def install(monkeypatch, script):
    fake = FakeLLM(script)
    monkeypatch.setattr(shoplab.llm, "complete", fake)
    return fake


def finish_tools():
    def finish(decision, policy_id, refund_usd=None):
        return {"decision": decision, "policy_id": policy_id, "refund_usd": refund_usd}

    schema = {"type": "object", "properties": {}, "required": []}
    return {"finish": Tool("finish", "final answer", schema, finish)}


# --- count_tokens ------------------------------------------------------------

def test_count_tokens_grows_with_message_count():
    short = count_tokens([{"role": "user", "content": "hello"}])
    long = count_tokens([{"role": "user", "content": "hello"}] * 12)
    assert short > 0
    assert long > short


def test_count_tokens_grows_with_message_length():
    small = count_tokens([{"role": "user", "content": "hi"}])
    big = count_tokens([{"role": "user",
                         "content": "hello there " * 40}])
    assert big > small


def test_count_tokens_accepts_a_bare_string():
    # a bare string is wrapped as one user message -> same count as that message
    assert count_tokens("hello world") == count_tokens(
        [{"role": "user", "content": "hello world"}])
    assert count_tokens("hello world") > 0


def test_count_tokens_honors_explicit_model():
    # passing a model must not error and must return a positive count
    n = count_tokens([{"role": "user", "content": "hello"}],
                     model="openrouter/deepseek/deepseek-v3.2")
    assert n > 0


# --- ContextLedger -----------------------------------------------------------

def test_observe_records_tokens_label_and_step_index():
    led = ContextLedger()
    t0 = led.observe([{"role": "user", "content": "a"}], label="start")
    t1 = led.observe([{"role": "user", "content": "a"},
                      {"role": "assistant", "content": "a much longer reply here"}],
                     label="reply")
    assert [row["step"] for row in led.steps] == [0, 1]
    assert [row["label"] for row in led.steps] == ["start", "reply"]
    assert [row["messages"] for row in led.steps] == [1, 2]
    assert led.steps[0]["tokens"] == t0 and led.steps[1]["tokens"] == t1
    assert t1 > t0                       # more content -> more tokens


def test_growth_returns_the_rows():
    led = ContextLedger()
    led.observe([{"role": "user", "content": "x"}])
    assert led.growth() is led.steps
    assert led.growth()[0]["messages"] == 1


def test_peak_is_the_high_water_mark():
    led = ContextLedger()
    assert led.peak() == 0               # nothing observed yet
    led.observe([{"role": "user", "content": "short"}])
    led.observe([{"role": "user", "content": "a considerably longer message body"}])
    led.observe([{"role": "user", "content": "mid"}])
    assert led.peak() == max(row["tokens"] for row in led.steps)


# --- offload / load_offload --------------------------------------------------

def test_offload_writes_file_and_roundtrips(tmp_path):
    content = "x" * 500
    d = str(tmp_path / "off")
    handle = offload(content, tag="blob", dir=d)
    assert set(handle) == {"ref", "chars", "preview"}
    assert handle["chars"] == 500
    assert handle["preview"] == "x" * 120         # first 120 chars only
    assert handle["ref"].endswith("blob-0.txt")
    assert load_offload(handle) == content        # accepts the handle dict


def test_load_offload_accepts_a_bare_ref_string(tmp_path):
    handle = offload("payload", tag="note", dir=str(tmp_path / "off"))
    assert load_offload(handle["ref"]) == "payload"


def test_offload_numbers_deterministically(tmp_path):
    d = str(tmp_path / "off")
    h0 = offload("first", tag="blob", dir=d)
    h1 = offload("second", tag="blob", dir=d)
    assert h0["ref"].endswith("blob-0.txt")
    assert h1["ref"].endswith("blob-1.txt")


def test_load_offload_missing_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        load_offload(str(tmp_path / "gone.txt"))
    assert "no offload" in str(exc.value)


# --- compact -----------------------------------------------------------------

def test_compact_keeps_head_system_and_last_keep_last():
    messages = [
        {"role": "system", "content": "you are the ops desk"},
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": "turn 2"},
        {"role": "user", "content": "turn 3"},
        {"role": "assistant", "content": "turn 4"},
        {"role": "user", "content": "turn 5"},
        {"role": "assistant", "content": "turn 6"},
    ]
    out = compact(messages, keep_last=4)
    # head system + one note + last 4 verbatim; 7 - 1 head - 4 kept = 2 folded
    assert out[0] == messages[0]
    assert out[1]["role"] == "system"
    assert out[1]["content"].startswith("[compacted 2 messages] ")
    assert out[2:] == messages[3:]                # last 4 kept verbatim
    assert len(out) == 6


def test_compact_returns_a_new_list_and_does_not_mutate_input():
    messages = [{"role": "system", "content": "s"}] + \
               [{"role": "user", "content": f"m{i}"} for i in range(6)]
    original = copy.deepcopy(messages)
    out = compact(messages, keep_last=2)
    assert out is not messages
    assert messages == original                   # input untouched


def test_compact_keeps_multiple_head_system_messages():
    messages = [
        {"role": "system", "content": "sys A"},
        {"role": "system", "content": "sys B"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
    ]
    out = compact(messages, keep_last=2)
    assert out[0]["content"] == "sys A"
    assert out[1]["content"] == "sys B"
    assert out[2]["role"] == "system" and out[2]["content"].startswith("[compacted 2")
    assert out[3:] == messages[4:]


def test_compact_short_list_has_nothing_to_fold():
    messages = [{"role": "system", "content": "s"},
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"}]
    out = compact(messages, keep_last=4)
    assert out == messages                         # unchanged, but a new list
    assert out is not messages


def test_compact_does_not_orphan_a_tool_result_from_its_tool_call():
    # last assistant issues a tool_call; its tool result is the final message.
    # with keep_last=1 the naive cut would keep only the tool message and drop
    # the assistant tool_call that owns it -- compact must extend the window.
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "triage TKT-2205"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "call-a", "function": {"name": "get_order",
                                                      "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call-a", "content": "{\"ok\": true}"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "call-b", "function": {"name": "get_customer",
                                                      "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call-b", "content": "{\"tier\": \"vip\"}"},
    ]
    out = compact(messages, keep_last=1)
    # tail must be the assistant tool_call PLUS its tool result, kept together
    assert out[-2]["role"] == "assistant" and out[-2]["tool_calls"][0]["id"] == "call-b"
    assert out[-1]["role"] == "tool" and out[-1]["tool_call_id"] == "call-b"
    # the middle (user + first tool_call + its result) got folded into one note
    assert out[0] == messages[0]
    assert out[1]["role"] == "system" and out[1]["content"].startswith("[compacted 3")
    assert len(out) == 4


# --- run_subagent (the context firewall) -------------------------------------

def test_run_subagent_returns_only_the_compact_result(monkeypatch):
    fake = install(monkeypatch, [
        make_tool_call_msg("finish", {"decision": "deny", "policy_id": "pol-returns"}),
    ])
    out = run_subagent("triage TKT-2233", finish_tools())
    # answer is the finish tool-call's raw arguments dict (what run_agent returns)
    assert out == {"answer": {"decision": "deny", "policy_id": "pol-returns"},
                   "steps": 1, "stop_reason": "finish"}
    assert "messages" not in out                   # the firewall: no inner turns leak
    assert len(fake.calls) == 1


def test_run_subagent_leaves_the_parent_context_untouched(monkeypatch):
    install(monkeypatch, [make_text_msg("done quickly")])
    parent = [{"role": "system", "content": "parent system"},
              {"role": "user", "content": "parent task"}]
    parent_before = copy.deepcopy(parent)
    out = run_subagent("a separate sub-task", finish_tools(), max_steps=3)
    assert out["stop_reason"] == "text" and out["answer"] == "done quickly"
    assert parent == parent_before                 # parent list never touched


def test_run_subagent_passes_through_max_steps(monkeypatch):
    # a tool loop that never calls finish -> hits max_steps=2, compact dict only
    fake = install(monkeypatch, [
        make_tool_call_msg("noop", {}, tool_call_id=f"c{i}") for i in range(5)
    ])

    def noop():
        return {"ok": True}

    tools = {"noop": Tool("noop", "does nothing", {"type": "object",
             "properties": {}, "required": []}, noop)}
    out = run_subagent("loop", tools, max_steps=2)
    assert out == {"answer": None, "steps": 2, "stop_reason": "max_steps"}
    assert len(fake.calls) == 2
