"""Scoring and evaluation harness for the ticket-triage task.

Chapter 04 grades the agent against the gold labels that
``shoplab.rules.decide`` computed: ``score_ticket`` compares one prediction
field by field (the sentinel region, byte-identical to the notebook),
``evaluate`` runs a candidate over a ticket list and aggregates accuracies
plus LLM spend, and ``load_run`` / ``compare_runs`` turn the saved JSON
artifacts under ``artifacts/runs/`` into small before/after comparisons.
"""

import json
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "runs"

METRICS = ("decision_acc", "policy_acc", "amount_acc", "exact_acc", "cost_usd")


# >>> shoplab.evals.score_ticket
def score_ticket(pred, gold) -> dict:
    """Field-by-field scores for one predicted decision against its gold label."""
    if not isinstance(pred, dict):
        return {"decision_correct": False, "policy_correct": False,
                "amount_correct": False, "exact": False}
    decision = pred.get("decision") == gold["decision"]
    policy = pred.get("policy_id") == gold["policy_id"]
    a, b = pred.get("refund_usd"), gold["refund_usd"]
    if a is None or b is None:
        amount = a is None and b is None        # both absent is a match
    else:
        amount = abs(a - b) <= 0.01             # a cent of float slack
    return {"decision_correct": decision, "policy_correct": policy,
            "amount_correct": amount, "exact": decision and policy and amount}
# <<< shoplab.evals.score_ticket


def evaluate(run_fn, tickets, *, name="run", save=True, verbose=True) -> dict:
    """Run ``run_fn(ticket) -> pred`` over tickets; aggregate accuracy and cost."""
    from shoplab.llm import LEDGER              # lazy: scoring alone needs no LLM
    ledger_start = len(LEDGER)
    rows = []
    for ticket in tickets:
        pred = run_fn(ticket)
        rows.append({"ticket_id": ticket["ticket_id"], "pred": pred,
                     "gold": ticket["gold"],
                     "scores": score_ticket(pred, ticket["gold"])})

    def acc(key):
        return round(sum(r["scores"][key] for r in rows) / len(rows), 4) if rows else 0.0

    result = {"name": name, "n": len(rows),
              "decision_acc": acc("decision_correct"),
              "policy_acc": acc("policy_correct"),
              "amount_acc": acc("amount_correct"),
              "exact_acc": acc("exact"),
              "cost_usd": round(sum(e["cost_usd"] for e in LEDGER[ledger_start:]), 6),
              "rows": rows}
    if save:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (RUNS_DIR / f"{name}.json").write_text(json.dumps(result, indent=2),
                                               encoding="utf-8")
    if verbose:
        print(f"{name}: n={result['n']}  decision {result['decision_acc']:.2f}  "
              f"policy {result['policy_acc']:.2f}  amount {result['amount_acc']:.2f}  "
              f"exact {result['exact_acc']:.2f}  cost ${result['cost_usd']:.6f}")
    return result


def load_run(name) -> dict:
    """Load a saved run from ``artifacts/runs/<name>.json``."""
    with open(RUNS_DIR / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def compare_runs(a: str, b: str) -> dict:
    """Metric deltas (b minus a) for two saved runs; prints the tickets that flipped."""
    run_a, run_b = load_run(a), load_run(b)
    deltas = {m: round(run_b[m] - run_a[m], 6) for m in METRICS}
    print(f"{'metric':<14}{a:>16}{b:>16}{'delta':>10}")
    for m in METRICS:
        print(f"{m:<14}{run_a[m]:>16.4f}{run_b[m]:>16.4f}{deltas[m]:>+10.4f}")
    exact_a = {r["ticket_id"]: r["scores"]["exact"] for r in run_a["rows"]}
    exact_b = {r["ticket_id"]: r["scores"]["exact"] for r in run_b["rows"]}
    for ticket_id in sorted(set(exact_a) & set(exact_b)):
        if exact_a[ticket_id] != exact_b[ticket_id]:
            direction = "fixed" if exact_b[ticket_id] else "broke"
            print(f"  {direction}: {ticket_id}")
    return deltas
