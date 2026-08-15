"""shoplab.controls: budget ceilings, atomic checkpoints, and approval gates."""

import json

import pytest

from shoplab.controls import (Budget, BudgetExceeded, Checkpoint,
                              console_approver, require_approval)
from shoplab.tools import Tool


# --- Budget ------------------------------------------------------------------

def test_charge_counts_and_accumulates_and_returns_self():
    b = Budget()
    assert b.charge(0.001) is b            # returns self for chaining
    b.charge(0.002)
    assert b.calls == 2
    assert b.cost_usd == pytest.approx(0.003)


def test_charge_none_cost_counts_a_call_without_dollars():
    b = Budget()
    b.charge()                             # default 0.0
    b.charge(None)                         # a call with no known cost
    assert b.calls == 2 and b.cost_usd == 0.0


def test_charge_trips_on_call_ceiling():
    b = Budget(max_calls=2)
    b.charge(0.0)
    b.charge(0.0)                          # second call is still within budget
    with pytest.raises(BudgetExceeded) as exc:
        b.charge(0.0)                      # third crosses it
    assert "call budget" in str(exc.value)
    assert b.calls == 3                    # the over-limit call is still counted


def test_charge_trips_on_cost_ceiling():
    b = Budget(max_cost_usd=0.01)
    b.charge(0.006)
    with pytest.raises(BudgetExceeded) as exc:
        b.charge(0.006)                    # 0.012 > 0.01
    assert "cost budget" in str(exc.value)


def test_remaining_are_none_when_unlimited():
    b = Budget()
    assert b.remaining_calls is None
    assert b.remaining_cost is None


def test_remaining_track_the_ceilings():
    b = Budget(max_calls=5, max_cost_usd=0.01)
    b.charge(0.004)
    assert b.remaining_calls == 4
    assert b.remaining_cost == pytest.approx(0.006)


def test_snapshot_shape_and_math():
    b = Budget(max_calls=3, max_cost_usd=0.02)
    b.charge(0.005)
    assert b.snapshot() == {"calls": 1, "cost_usd": 0.005,
                            "remaining_calls": 2, "remaining_cost": 0.015}


def test_snapshot_reports_none_remaining_when_unlimited():
    snap = Budget().charge(0.001).snapshot()
    assert snap["remaining_calls"] is None and snap["remaining_cost"] is None


# --- Checkpoint --------------------------------------------------------------

STATE = {"messages": [{"role": "user", "content": "triage TKT-2205"}],
         "step": 3, "meta": {"ticket_id": "TKT-2205"}}


def test_save_load_roundtrip(tmp_path):
    path = Checkpoint.save(STATE, tmp_path / "ckpt.json")
    assert path == tmp_path / "ckpt.json" and path.exists()
    loaded = Checkpoint.load(path)
    assert loaded == STATE


def test_save_fills_defaults_for_missing_keys(tmp_path):
    path = Checkpoint.save({}, tmp_path / "empty.json")
    assert Checkpoint.load(path) == {"messages": [], "step": 0, "meta": {}}


def test_save_creates_parent_directories(tmp_path):
    path = Checkpoint.save(STATE, tmp_path / "runs" / "deep" / "ckpt.json")
    assert path.exists()
    assert json.loads(path.read_text())["step"] == 3


def test_save_leaves_no_partial_tmp_file(tmp_path):
    path = Checkpoint.save(STATE, tmp_path / "ckpt.json")
    # atomic replace: exactly the final file, no .tmp sibling left behind
    assert not (tmp_path / "ckpt.json.tmp").exists()
    assert list(p.name for p in tmp_path.iterdir()) == [path.name]


def test_load_missing_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        Checkpoint.load(tmp_path / "nope.json")
    assert "no checkpoint" in str(exc.value)


# --- require_approval --------------------------------------------------------

class _Boom(Exception):
    pass


def _sentinel_tool():
    """A risky tool whose fn explodes if it is ever actually called."""
    def fn(**kwargs):
        raise _Boom("the underlying tool ran despite denial")

    schema = {"type": "object",
              "properties": {"order_id": {"type": "string"},
                             "amount_usd": {"type": "number"}},
              "required": ["order_id", "amount_usd"]}
    return Tool("issue_refund", "Send money back. Irreversible.", schema, fn, risky=True)


def test_require_approval_denied_does_not_call_the_tool():
    gated = require_approval(_sentinel_tool(), lambda name, args: False)
    result = gated.fn(order_id="ORD-7301", amount_usd=99.0)   # must NOT raise _Boom
    assert result == {"blocked": True, "reason": "approval denied"}


def test_require_approval_none_verdict_is_a_denial():
    gated = require_approval(_sentinel_tool(), lambda name, args: None)
    assert gated.fn(order_id="ORD-7301", amount_usd=1.0)["blocked"] is True


def test_require_approval_granted_runs_the_tool():
    seen = {}

    def fn(order_id, amount_usd):
        seen.update(order_id=order_id, amount_usd=amount_usd)
        return {"ok": True, "refund_id": "REF-1001"}

    tool = Tool("issue_refund", "Send money.", {"type": "object", "properties": {},
                                                "required": []}, fn, risky=True)
    gated = require_approval(tool, lambda name, args: True)
    assert gated.fn(order_id="ORD-7301", amount_usd=42.0) == {
        "ok": True, "refund_id": "REF-1001"}
    assert seen == {"order_id": "ORD-7301", "amount_usd": 42.0}


def test_require_approval_hands_the_call_to_the_approver():
    calls = []
    gated = require_approval(_sentinel_tool(),
                             lambda name, args: calls.append((name, args)) or False)
    gated.fn(order_id="ORD-7301", amount_usd=5.0)
    assert calls == [("issue_refund", {"order_id": "ORD-7301", "amount_usd": 5.0})]


def test_require_approval_preserves_the_wrapped_metadata():
    original = _sentinel_tool()
    gated = require_approval(original, lambda name, args: True)
    assert isinstance(gated, Tool)
    assert gated.name == original.name
    assert gated.description == original.description
    assert gated.params is original.params
    assert gated.risky is True
    assert gated.fn is not original.fn          # a new, wrapping fn


def test_console_approver_reads_yes_no(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda: "y")
    assert console_approver("issue_refund", {"order_id": "ORD-7301"}) is True
    assert "issue_refund" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda: "no")
    assert console_approver("issue_refund", {}) is False
