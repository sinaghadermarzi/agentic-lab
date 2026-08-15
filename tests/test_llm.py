"""shoplab.llm: parse_json_loose fixtures, ledger math, and stubbed model calls.

No test here touches the network: complete()/llm() run against a monkeypatched
litellm.completion returning the SimpleNamespace fakes from tests/fakes.py.
"""

import os

import litellm
import pytest

import fakes
from shoplab import llm


# --- parse_json_loose --------------------------------------------------------

def test_parse_bare_object():
    assert llm.parse_json_loose('{"a": 1}') == {"a": 1}


def test_parse_fenced_json():
    assert llm.parse_json_loose('```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}


def test_parse_fence_without_language_tag():
    assert llm.parse_json_loose('```\n[1, 2]\n```') == [1, 2]


def test_parse_prose_wrapped():
    text = 'Sure! Here is the verdict: {"decision": "deny"} -- hope that helps.'
    assert llm.parse_json_loose(text) == {"decision": "deny"}


def test_parse_nested_braces_inside_strings():
    text = '{"s": "a } b { c \\" d", "n": 2}'
    assert llm.parse_json_loose(text) == {"s": 'a } b { c " d', "n": 2}


def test_parse_trailing_garbage_after_object():
    assert llm.parse_json_loose('{"a": 1}}} and more words') == {"a": 1}


def test_parse_list_at_top_level():
    text = 'result: [1, 2, {"x": "y"}] done'
    assert llm.parse_json_loose(text) == [1, 2, {"x": "y"}]


def test_parse_garbage_raises_value_error():
    with pytest.raises(ValueError):
        llm.parse_json_loose("no json here at all")


def test_parse_unbalanced_raises_value_error():
    with pytest.raises(ValueError):
        llm.parse_json_loose('{"a": 1')


# --- usage_summary -----------------------------------------------------------

def test_usage_summary_totals(monkeypatch):
    rows = [
        {"model": "m", "prompt_tokens": 10, "completion_tokens": 5,
         "cost_usd": 0.5, "seconds": 0.1},
        {"model": "m", "prompt_tokens": 30, "completion_tokens": 7,
         "cost_usd": 0.25, "seconds": 0.2},
    ]
    monkeypatch.setattr(llm, "LEDGER", rows)
    assert llm.usage_summary() == {
        "calls": 2, "prompt_tokens": 40, "completion_tokens": 12, "cost_usd": 0.75}


def test_usage_summary_empty(monkeypatch):
    monkeypatch.setattr(llm, "LEDGER", [])
    assert llm.usage_summary() == {
        "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0}


# --- complete / llm against a stubbed litellm.completion ---------------------

@pytest.fixture
def stub(monkeypatch):
    """Replace litellm.completion; capture kwargs, return a canned response."""
    captured = {}

    def fake_completion(**kw):
        captured.update(kw)
        return fake_completion.response

    fake_completion.response = fakes.make_text_msg("hi")
    monkeypatch.setattr(litellm, "completion", fake_completion)
    monkeypatch.setattr(llm, "LEDGER", [])
    return captured, fake_completion


def test_complete_records_ledger_row(stub):
    captured, _ = stub
    r = llm.complete([{"role": "user", "content": "hello"}])
    assert r.choices[0].message.content == "hi"
    assert len(llm.LEDGER) == 1
    row = llm.LEDGER[0]
    assert row["prompt_tokens"] == 7 and row["completion_tokens"] == 3
    assert row["cost_usd"] == pytest.approx(0.000008)
    assert row["seconds"] >= 0
    assert row["model"] == captured["model"]


def test_complete_default_model_comes_from_env(stub):
    captured, _ = stub
    llm.complete([{"role": "user", "content": "x"}])
    assert captured["model"] == os.environ.get("MODEL", llm.DEFAULT_MODEL)
    llm.complete([{"role": "user", "content": "x"}], model="other/model")
    assert captured["model"] == "other/model"


def test_complete_passes_tools_only_when_given(stub):
    captured, _ = stub
    llm.complete([{"role": "user", "content": "x"}])
    assert "tools" not in captured
    tools = [{"type": "function", "function": {"name": "t"}}]
    llm.complete([{"role": "user", "content": "x"}], tools=tools)
    assert captured["tools"] == tools


def test_complete_none_cost_becomes_zero(stub):
    _, fake_completion = stub
    fake_completion.response = fakes.make_text_msg("hi", cost=None)
    llm.complete([{"role": "user", "content": "x"}])
    assert llm.LEDGER[-1]["cost_usd"] == 0


def test_llm_builds_messages_and_returns_content(stub):
    captured, _ = stub
    assert llm.llm("hello", system="be brief") == "hi"
    assert captured["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hello"},
    ]
    assert llm.llm("hello") == "hi"
    assert captured["messages"] == [{"role": "user", "content": "hello"}]
