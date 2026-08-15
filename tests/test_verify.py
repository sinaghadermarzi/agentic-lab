"""shoplab.verify: the LLM judge (stubbed), the refine loop, and the cheap
deterministic decision check.

The judge tests never touch the network: shoplab.llm.complete is monkeypatched
to return the SimpleNamespace fakes from tests/fakes.py. check_decision runs
against the real world data and rules cascade.
"""

import pytest

import fakes
import shoplab.llm
from shoplab import verify, world
from shoplab.rules import decide


# --- judge (stubbed model) ---------------------------------------------------

def stub_reply(monkeypatch, content, capture=None):
    """Make shoplab.llm.complete return one canned assistant message."""
    def fake_complete(messages, **kw):
        if capture is not None:
            capture["messages"] = messages
            capture["kw"] = kw
        return fakes.make_text_msg(content)

    monkeypatch.setattr(shoplab.llm, "complete", fake_complete)


def test_judge_parses_a_clean_verdict(monkeypatch):
    stub_reply(monkeypatch, '{"pass": true, "score": 0.92, "reasons": "cites the policy"}')
    verdict = verify.judge("q", "a", "must cite a policy id")
    assert verdict == {"pass": True, "score": 0.92, "reasons": "cites the policy"}


def test_judge_parses_a_fenced_verdict(monkeypatch):
    stub_reply(monkeypatch,
               'Here you go:\n```json\n{"pass": false, "score": 0.3, "reasons": "no id"}\n```')
    verdict = verify.judge("q", "a", "rubric")
    assert verdict["pass"] is False and verdict["score"] == pytest.approx(0.3)
    assert verdict["reasons"] == "no id"


def test_judge_survives_junk_output(monkeypatch):
    stub_reply(monkeypatch, "I cannot possibly grade that, sorry.")
    verdict = verify.judge("q", "a", "rubric")
    assert verdict["pass"] is False and verdict["score"] == 0.0
    assert verdict["reasons"].startswith("unparseable:")


def test_judge_rejects_non_object_json(monkeypatch):
    stub_reply(monkeypatch, "[1, 2, 3]")             # valid JSON, wrong shape
    verdict = verify.judge("q", "a", "rubric")
    assert verdict["pass"] is False and verdict["score"] == 0.0
    assert verdict["reasons"].startswith("unparseable:")


def test_judge_coerces_verdict_types(monkeypatch):
    # score given as a string, pass given as truthy int -> coerced cleanly
    stub_reply(monkeypatch, '{"pass": 1, "score": "0.5", "reasons": 42}')
    verdict = verify.judge("q", "a", "rubric")
    assert verdict == {"pass": True, "score": 0.5, "reasons": "42"}


def test_judge_defaults_to_the_strong_model(monkeypatch):
    monkeypatch.delenv("STRONG_MODEL", raising=False)
    capture = {}
    stub_reply(monkeypatch, '{"pass": true, "score": 1.0, "reasons": "ok"}', capture)
    verify.judge("q", "a", "rubric")
    assert capture["kw"]["model"] == verify.DEFAULT_STRONG_MODEL
    # rubric and answer are embedded in the prompt sent to the grader
    user_prompt = capture["messages"][-1]["content"]
    assert "rubric" in user_prompt and "a" in user_prompt


def test_judge_explicit_model_overrides_the_default(monkeypatch):
    capture = {}
    stub_reply(monkeypatch, '{"pass": true, "score": 1.0, "reasons": "ok"}', capture)
    verify.judge("q", "a", "rubric", model="openrouter/some/other-model")
    assert capture["kw"]["model"] == "openrouter/some/other-model"


# --- refine_until ------------------------------------------------------------

def test_refine_stops_on_first_pass():
    seen_feedback = []

    def draft_fn(feedback):
        seen_feedback.append(feedback)
        return "draft-0"

    def critique_fn(draft):
        return {"pass": True, "score": 1.0}

    out = verify.refine_until(draft_fn, critique_fn, max_rounds=3)
    assert out["result"] == "draft-0"
    assert out["rounds"] == 1
    assert len(out["history"]) == 1 and out["history"][0]["pass"] is True
    assert seen_feedback == [None]              # drafted once, never redrafted


def test_refine_runs_max_rounds_when_never_passing():
    drafts = []

    def draft_fn(feedback):
        drafts.append(feedback)
        return f"draft-{len(drafts)}"

    def critique_fn(draft):
        return {"pass": False, "score": 0.1, "reasons": f"still wrong: {draft}"}

    out = verify.refine_until(draft_fn, critique_fn, max_rounds=3)
    assert out["rounds"] == 3
    assert len(out["history"]) == 3
    assert all(v["pass"] is False for v in out["history"])
    # never passing: draft_fn runs max_rounds+1 times (1 initial + 1 redraft per
    # failing round), so the returned result is the final, uncritiqued redraft
    assert out["result"] == "draft-4"


def test_refine_threads_the_prior_verdict_into_draft_fn():
    seen_feedback = []

    def draft_fn(feedback):
        seen_feedback.append(feedback)
        return "draft"

    verdicts = [{"pass": False, "score": 0.2, "reasons": "add the amount"},
                {"pass": True, "score": 1.0, "reasons": "good"}]

    def critique_fn(draft):
        return verdicts[len(seen_feedback) - 1]

    out = verify.refine_until(draft_fn, critique_fn, max_rounds=5)
    assert out["rounds"] == 2
    # first draft gets None, the redraft gets the exact prior (failing) verdict
    assert seen_feedback[0] is None
    assert seen_feedback[1] == {"pass": False, "score": 0.2, "reasons": "add the amount"}


# --- check_decision ----------------------------------------------------------

def _ticket_context(ticket_id):
    tickets = world.load_tickets()
    rows = tickets["train"] + tickets["dev"] + tickets["test"]
    ticket = next(t for t in rows if t["ticket_id"] == ticket_id)
    order = {o["order_id"]: o for o in world.load_orders()}[ticket["order_id"]]
    customer = {c["customer_id"]: c for c in world.load_customers()}[ticket["customer_id"]]
    return ticket, order, customer


def test_check_decision_agrees_with_gold_on_a_real_ticket():
    ticket, order, customer = _ticket_context("TKT-2205")
    gold = decide(ticket, order, customer)
    out = verify.check_decision(dict(gold), ticket, order, customer)
    assert out["agrees"] is True
    assert out["mismatch"] == []
    assert out["gold"] == gold
    assert out["gold"]["decision"] == "partial_refund"     # per docs/WORLD.md


def test_check_decision_agrees_within_a_cent():
    ticket, order, customer = _ticket_context("TKT-2205")
    gold = decide(ticket, order, customer)
    pred = {**gold, "refund_usd": gold["refund_usd"] + 0.005}
    assert verify.check_decision(pred, ticket, order, customer)["agrees"] is True


def test_check_decision_flags_a_wrong_decision():
    ticket, order, customer = _ticket_context("TKT-2205")
    gold = decide(ticket, order, customer)
    pred = {**gold, "decision": "approve_refund"}          # mangled
    out = verify.check_decision(pred, ticket, order, customer)
    assert out["agrees"] is False
    assert out["mismatch"] == ["decision"]


def test_check_decision_flags_an_off_by_two_cents_amount():
    ticket, order, customer = _ticket_context("TKT-2205")
    gold = decide(ticket, order, customer)
    pred = {**gold, "refund_usd": gold["refund_usd"] + 0.02}
    out = verify.check_decision(pred, ticket, order, customer)
    assert out["agrees"] is False and out["mismatch"] == ["refund_usd"]


def test_check_decision_none_pred_disagrees_on_every_field():
    ticket, order, customer = _ticket_context("TKT-2205")
    out = verify.check_decision(None, ticket, order, customer)
    assert out["agrees"] is False
    assert out["mismatch"] == ["decision", "policy_id", "refund_usd"]
    assert out["pred"] is None


def test_check_decision_garbage_pred_disagrees():
    ticket, order, customer = _ticket_context("TKT-2205")
    out = verify.check_decision("approve_refund", ticket, order, customer)
    assert out["agrees"] is False
    assert out["mismatch"] == ["decision", "policy_id", "refund_usd"]
