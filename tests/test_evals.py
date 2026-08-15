"""shoplab.evals: the score_ticket truth table and the evaluate/compare harness."""

import pytest

from shoplab import world
from shoplab.evals import RUNS_DIR, compare_runs, evaluate, load_run, score_ticket

GOLD = {"decision": "partial_refund", "policy_id": "pol-restocking",
        "refund_usd": 260.10}
GOLD_NONE = {"decision": "deny", "policy_id": "pol-returns", "refund_usd": None}

ALL_FALSE = {"decision_correct": False, "policy_correct": False,
             "amount_correct": False, "exact": False}


# --- score_ticket truth table ------------------------------------------------

def test_none_pred_scores_all_false():
    assert score_ticket(None, GOLD) == ALL_FALSE


def test_non_dict_pred_scores_all_false():
    assert score_ticket("partial_refund", GOLD) == ALL_FALSE
    assert score_ticket(["partial_refund"], GOLD) == ALL_FALSE


def test_perfect_pred_is_exact():
    assert score_ticket(dict(GOLD), GOLD) == {
        "decision_correct": True, "policy_correct": True,
        "amount_correct": True, "exact": True}


def test_wrong_decision_alone_kills_exact():
    assert score_ticket({**GOLD, "decision": "deny"}, GOLD) == {
        "decision_correct": False, "policy_correct": True,
        "amount_correct": True, "exact": False}


def test_right_decision_wrong_policy():
    assert score_ticket({**GOLD, "policy_id": "pol-returns"}, GOLD) == {
        "decision_correct": True, "policy_correct": False,
        "amount_correct": True, "exact": False}


def test_amounts_both_none_match():
    scores = score_ticket(dict(GOLD_NONE), GOLD_NONE)
    assert scores["amount_correct"] is True and scores["exact"] is True


def test_amount_one_sided_none_fails():
    assert score_ticket({**GOLD_NONE, "refund_usd": 10.0},
                        GOLD_NONE)["amount_correct"] is False
    assert score_ticket({**GOLD, "refund_usd": None}, GOLD)["amount_correct"] is False


def test_amount_near_equal_within_a_cent_counts():
    scores = score_ticket({**GOLD, "refund_usd": 260.105}, GOLD)
    assert scores["amount_correct"] is True and scores["exact"] is True


def test_amount_off_by_two_cents_fails():
    scores = score_ticket({**GOLD, "refund_usd": 260.12}, GOLD)
    assert scores["amount_correct"] is False and scores["exact"] is False


def test_missing_pred_keys_do_not_crash():
    assert score_ticket({}, GOLD) == ALL_FALSE


# --- evaluate / load_run / compare_runs --------------------------------------

TRAIN3 = world.load_tickets()["train"][:3]


def gold_fn(ticket):
    """A perfect candidate: parrot the gold label."""
    return dict(ticket["gold"])


def flawed_fn(ticket):
    """Gold everywhere except one wrong decision on the second ticket."""
    pred = dict(ticket["gold"])
    if ticket["ticket_id"] == TRAIN3[1]["ticket_id"]:
        pred["decision"] = "deny" if pred["decision"] != "deny" else "escalate"
    return pred


def test_evaluate_aggregates_and_rows_shape():
    result = evaluate(flawed_fn, TRAIN3, name="tmp-test-nosave",
                      save=False, verbose=False)
    assert result["name"] == "tmp-test-nosave" and result["n"] == 3
    assert result["decision_acc"] == pytest.approx(2 / 3, abs=1e-4)
    assert result["policy_acc"] == 1.0
    assert result["amount_acc"] == 1.0
    assert result["exact_acc"] == pytest.approx(2 / 3, abs=1e-4)
    assert result["cost_usd"] == 0.0            # the stub makes no LLM calls
    assert not (RUNS_DIR / "tmp-test-nosave.json").exists()
    assert [r["ticket_id"] for r in result["rows"]] == [
        t["ticket_id"] for t in TRAIN3]
    for row, ticket in zip(result["rows"], TRAIN3):
        assert set(row) == {"ticket_id", "pred", "gold", "scores"}
        assert row["gold"] == ticket["gold"]
        assert set(row["scores"]) == {"decision_correct", "policy_correct",
                                      "amount_correct", "exact"}


def test_evaluate_verbose_prints_one_summary_line(capsys):
    evaluate(gold_fn, TRAIN3, name="tmp-test-verbose", save=False, verbose=True)
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert "tmp-test-verbose" in out and "exact" in out


def test_save_load_and_compare_runs(capsys):
    name_a, name_b = "tmp-test-a", "tmp-test-b"
    try:
        evaluate(gold_fn, TRAIN3, name=name_a, save=True, verbose=False)
        evaluate(flawed_fn, TRAIN3, name=name_b, save=True, verbose=False)
        assert (RUNS_DIR / f"{name_a}.json").exists()

        loaded = load_run(name_a)
        assert loaded["n"] == 3 and loaded["exact_acc"] == 1.0

        deltas = compare_runs(name_a, name_b)
        assert deltas["decision_acc"] == pytest.approx(-1 / 3, abs=1e-3)
        assert deltas["exact_acc"] == pytest.approx(-1 / 3, abs=1e-3)
        assert deltas["policy_acc"] == 0.0
        assert deltas["amount_acc"] == 0.0
        assert deltas["cost_usd"] == 0.0

        out = capsys.readouterr().out
        assert TRAIN3[1]["ticket_id"] in out    # the flipped ticket is listed
        assert "broke" in out
    finally:
        for name in (name_a, name_b):
            (RUNS_DIR / f"{name}.json").unlink(missing_ok=True)
