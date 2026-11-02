"""shoplab.bridge: the OpenAI-compatible model door and the tool door, offline.

The model behind the door is a scripted fake patched over ``litellm.completion``,
so ``shoplab.llm.complete`` still runs for real and still writes its LEDGER row:
that is the property chapter 19 relies on when pi, not Python, drives the loop.
"""

import json

import httpx
import pytest

import shoplab.llm
from fakes import make_text_msg, make_tool_call_msg
from shoplab.bridge import DeskBridge, normalize_messages, sse_chunks
from shoplab.tools import Ledger, standard_tools


def parse_sse(text):
    """The data payloads of an SSE body, in order ('[DONE]' kept as a string)."""
    out = []
    for frame in text.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        assert frame.startswith("data: ")
        data = frame[len("data: "):]
        out.append(data if data == "[DONE]" else json.loads(data))
    return out


class ScriptedCompletion:
    """Stands in for litellm.completion: scripted responses, recorded kwargs."""

    def __init__(self, script):
        self.script, self.calls = list(script), []

    def __call__(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def ledger():
    return Ledger()


@pytest.fixture
def bridge(ledger):
    with DeskBridge(standard_tools(ledger), model="fake/model") as b:
        yield b


def script(monkeypatch, items):
    fake = ScriptedCompletion(items)
    monkeypatch.setattr(shoplab.llm.litellm, "completion", fake)
    return fake


# -- sse_chunks ---------------------------------------------------------------

def test_sse_chunks_text_answer_is_role_content_then_finish_then_done():
    frames = parse_sse("".join(sse_chunks({"content": "hello"}, model="m")))
    assert frames[-1] == "[DONE]"
    first, finish = frames[0], frames[1]
    assert first["object"] == "chat.completion.chunk"
    assert first["choices"][0]["delta"] == {"role": "assistant", "content": "hello"}
    assert first["choices"][0]["finish_reason"] is None
    assert finish["choices"][0]["finish_reason"] == "stop"
    assert "usage" not in finish
    assert len(frames) == 3


def test_sse_chunks_tool_calls_are_indexed_and_finish_with_usage():
    msg = {"content": None, "tool_calls": [
        {"id": "c1", "function": {"name": "get_order", "arguments": '{"order_id": "ORD-7301"}'}},
        {"id": "c2", "function": {"name": "get_customer", "arguments": ""}}]}
    usage = {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}
    frames = parse_sse("".join(sse_chunks(msg, model="m", usage=usage)))
    assert frames[0]["choices"][0]["delta"]["content"] == ""
    calls = [f["choices"][0]["delta"]["tool_calls"][0] for f in frames[1:3]]
    assert [c["index"] for c in calls] == [0, 1]
    assert [c["id"] for c in calls] == ["c1", "c2"]
    assert calls[0]["function"] == {"name": "get_order", "arguments": '{"order_id": "ORD-7301"}'}
    assert calls[1]["function"]["arguments"] == "{}"      # empty args become an empty object
    assert frames[3]["choices"][0]["finish_reason"] == "tool_calls"
    assert frames[3]["usage"] == usage
    assert frames[4] == "[DONE]"
    assert len({f["id"] for f in frames[:4]}) == 1          # one id across the stream


def test_sse_chunks_explicit_finish_reason_wins():
    frames = parse_sse("".join(sse_chunks({"content": "cut"}, model="m",
                                          finish_reason="length")))
    assert frames[1]["choices"][0]["finish_reason"] == "length"


# -- normalize_messages ---------------------------------------------------------

def test_normalize_messages_maps_developer_parts_and_keeps_tool_ids():
    raw = [
        {"role": "developer", "content": "be terse"},
        {"role": "user", "content": [{"type": "text", "text": "Ticket "},
                                     {"type": "text", "text": "TKT-2205"},
                                     {"type": "image_url", "image_url": {"url": "x"}}]},
        {"role": "assistant", "content": None, "reasoning_content": "hmm",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "get_order", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "get_order",
         "content": [{"type": "text", "text": '{"ok": true}'}]},
    ]
    out = normalize_messages(raw)
    assert out[0] == {"role": "system", "content": "be terse"}
    assert out[1] == {"role": "user", "content": "Ticket TKT-2205"}
    assert out[2]["content"] is None and "reasoning_content" not in out[2]
    assert out[2]["tool_calls"][0]["function"]["name"] == "get_order"
    assert out[3] == {"role": "tool", "content": '{"ok": true}', "tool_call_id": "c1"}


# -- the model door -------------------------------------------------------------

def test_streaming_chat_goes_through_complete_and_the_ledger(monkeypatch, bridge):
    fake = script(monkeypatch, [make_tool_call_msg("get_order", {"order_id": "ORD-7301"},
                                                   tool_call_id="call-9")])
    rows_before = len(shoplab.llm.LEDGER)
    body = {"model": "larkspur-desk", "stream": True, "max_completion_tokens": 32000,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "system", "content": "desk"},
                         {"role": "user", "content": "triage"}],
            "tools": [{"type": "function", "function": {"name": "get_order",
                                                        "parameters": {"type": "object"}}}]}
    r = httpx.post(bridge.url + "/v1/chat/completions", json=body, timeout=10)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = parse_sse(r.text)
    call = frames[1]["choices"][0]["delta"]["tool_calls"][0]
    assert call["id"] == "call-9" and call["function"]["name"] == "get_order"
    assert frames[-2]["choices"][0]["finish_reason"] == "tool_calls"
    assert frames[-2]["usage"]["prompt_tokens"] == 7
    # the request reached litellm through shoplab.llm.complete, course defaults intact
    kw = fake.calls[0]
    assert kw["model"] == "fake/model" and kw["temperature"] == 0
    assert kw["max_tokens"] == 1000                      # the bridge's, not the client's
    assert kw["messages"][1] == {"role": "user", "content": "triage"}
    assert len(shoplab.llm.LEDGER) == rows_before + 1
    assert bridge.calls[-1]["door"] == "model"
    assert bridge.calls[-1]["tool_calls"] == ["get_order"]


def test_non_streaming_chat_returns_a_completion_object(monkeypatch, bridge):
    script(monkeypatch, [make_text_msg("partial_refund")])
    r = httpx.post(bridge.url + "/v1/chat/completions",
                   json={"messages": [{"role": "user", "content": "hi"}]}, timeout=10)
    data = r.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "partial_refund"
    assert data["choices"][0]["finish_reason"] == "stop"


def test_empty_tools_list_is_sent_as_no_tools(monkeypatch, bridge):
    fake = script(monkeypatch, [make_text_msg("ok")])
    httpx.post(bridge.url + "/v1/chat/completions",
               json={"messages": [{"role": "user", "content": "hi"}], "tools": []}, timeout=10)
    assert "tools" not in fake.calls[0]


def test_upstream_failure_is_an_openai_style_error(monkeypatch, bridge):
    script(monkeypatch, [RuntimeError("provider down")])
    r = httpx.post(bridge.url + "/v1/chat/completions",
                   json={"stream": True, "messages": [{"role": "user", "content": "hi"}]},
                   timeout=10)
    assert r.status_code == 502
    assert "provider down" in r.json()["error"]["message"]


def test_stop_with_tool_calls_is_reported_as_tool_calls(monkeypatch, bridge):
    resp = make_tool_call_msg("get_order", {"order_id": "ORD-7301"})
    resp.choices[0].finish_reason = "stop"             # a provider quirk the bridge corrects
    script(monkeypatch, [resp])
    r = httpx.post(bridge.url + "/v1/chat/completions",
                   json={"stream": True, "messages": [{"role": "user", "content": "x"}]},
                   timeout=10)
    assert parse_sse(r.text)[-2]["choices"][0]["finish_reason"] == "tool_calls"


# -- the tool door --------------------------------------------------------------

def test_catalog_is_the_standard_toolset_as_data(bridge):
    cat = httpx.get(bridge.url + "/tools", timeout=10).json()
    assert [t["name"] for t in cat] == list(standard_tools())
    risky = {t["name"] for t in cat if t["risky"]}
    assert risky == {"issue_refund", "create_replacement"}
    finish = next(t for t in cat if t["name"] == "finish")
    assert finish["parameters"]["required"] == ["decision", "policy_id"]


def test_tool_door_runs_run_tool_and_errors_stay_results(bridge):
    ok = httpx.post(bridge.url + "/tools/get_order", json={"order_id": "ORD-7301"}, timeout=10)
    assert ok.status_code == 200 and ok.json()["order_id"] == "ORD-7301"
    missing = httpx.post(bridge.url + "/tools/teleport", json={}, timeout=10)
    assert missing.status_code == 200
    assert missing.json() == {"error": "unknown tool teleport"}
    bad = httpx.post(bridge.url + "/tools/get_order", json={"oops": 1}, timeout=10)
    assert "TypeError" in bad.json()["error"]
    assert [c["error"] for c in bridge.calls] == [False, True, True]


def test_risky_tool_through_the_door_writes_the_python_ledger(bridge, ledger):
    r = httpx.post(bridge.url + "/tools/issue_refund",
                   json={"order_id": "ORD-7312", "amount_usd": 170.99, "reason": "restocking"},
                   timeout=10)
    assert r.json()["ok"] is True
    assert ledger.entries[0]["kind"] == "issue_refund"
    assert ledger.entries[0]["amount_usd"] == 170.99


def test_bridge_start_stop_is_idempotent_and_frees_the_port(ledger):
    b = DeskBridge(standard_tools(ledger)).start()
    url = b.url
    assert httpx.get(url + "/v1/models", timeout=10).json()["data"][0]["id"] == "larkspur-desk"
    b.start()                                            # second start is a no-op
    b.stop()
    with pytest.raises(httpx.HTTPError):
        httpx.get(url + "/tools", timeout=2)
