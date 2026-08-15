"""Verification for the ops desk: an LLM judge, an evaluator-optimizer loop, and
a deterministic decision check.

Chapter 06 builds this module -- three ways to catch a wrong answer before it
ships. ``judge`` is LLM-as-judge: a strong model grades an answer against a
rubric and returns a structured verdict. ``refine_until`` is the
evaluator-optimizer pattern: draft, critique, redraft until a verdict passes.
``check_decision`` is the cheap, deterministic counterweight to ``judge`` -- it
recomputes the gold refund decision with ``shoplab.rules.decide`` and flags any
field the agent's prediction contradicts, no model call required.
"""

import os

import shoplab.llm
import shoplab.rules

# The grader's default: a model a cut above the one under test. STRONG_MODEL
# (from .env) overrides it; unset or empty falls back to this course default.
DEFAULT_STRONG_MODEL = "openrouter/deepseek/deepseek-v4-flash"

_JUDGE_SYSTEM = (
    "You are a strict grader. Read the question, the candidate answer, and the "
    "rubric, then decide whether the answer satisfies the rubric. Reply with a "
    'single JSON object and nothing else: {"pass": true|false, "score": 0.0-1.0, '
    '"reasons": "one or two sentences"}. score is how fully the answer meets the '
    "rubric (1.0 perfect); pass is true only when you would ship the answer as is."
)


def judge(question, answer, rubric, *, model=None) -> dict:
    """LLM-as-judge: grade ``answer`` to ``question`` against ``rubric``.

    Returns ``{"pass": bool, "score": float in 0..1, "reasons": str}``. Uses the
    strong model (``STRONG_MODEL`` env, else the course default) so the grader
    outranks the model under test. Junk output never raises: an unparseable reply
    becomes ``{"pass": False, "score": 0.0, "reasons": "unparseable: ..."}``.
    """
    model = model or os.environ.get("STRONG_MODEL") or DEFAULT_STRONG_MODEL
    prompt = (f"QUESTION:\n{question}\n\n"
              f"CANDIDATE ANSWER:\n{answer}\n\n"
              f"RUBRIC (the answer must satisfy this):\n{rubric}\n\n"
              "Return your JSON verdict now.")
    reply = shoplab.llm.complete(
        [{"role": "system", "content": _JUDGE_SYSTEM},
         {"role": "user", "content": prompt}],
        model=model).choices[0].message.content
    try:
        verdict = shoplab.llm.parse_json_loose(reply or "")
        if not isinstance(verdict, dict):
            raise ValueError(f"expected a JSON object, got {type(verdict).__name__}")
        score = float(verdict.get("score", 0.0) or 0.0)
    except (ValueError, TypeError) as exc:
        return {"pass": False, "score": 0.0, "reasons": f"unparseable: {exc}"}
    return {"pass": bool(verdict.get("pass")), "score": score,
            "reasons": str(verdict.get("reasons", ""))}


def refine_until(draft_fn, critique_fn, *, max_rounds=3) -> dict:
    """Evaluator-optimizer loop: draft, critique, redraft until a verdict passes.

    ``draft_fn(feedback)`` produces a candidate -- ``feedback`` is ``None`` on the
    first call, else the previous verdict dict, so the drafter can act on the
    critique. ``critique_fn(draft)`` returns a verdict dict; a truthy
    ``verdict["pass"]`` stops the loop. Returns
    ``{"result": last_draft, "rounds": rounds_run, "history": [verdicts...]}``.
    """
    draft = draft_fn(None)
    history, rounds = [], 0
    for rounds in range(1, max_rounds + 1):
        verdict = critique_fn(draft)
        history.append(verdict)
        if verdict.get("pass"):
            break
        draft = draft_fn(verdict)
    return {"result": draft, "rounds": rounds, "history": history}


def _amounts_agree(a, b) -> bool:
    """Match ``score_ticket``: both absent match; else equal within a cent."""
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(a - b) <= 0.01
    except TypeError:
        return False


def check_decision(pred, ticket, order, customer) -> dict:
    """Cheap deterministic verifier: does ``pred`` match ``rules.decide``'s gold?

    Recomputes the gold decision for this ticket and compares the three fields
    (``decision``, ``policy_id``, ``refund_usd``). Returns ``{"agrees": bool,
    "gold": {...}, "pred": pred, "mismatch": [fields...]}``. A ``None`` or non-dict
    prediction disagrees on every field. Unlike ``judge`` this calls no model -- it
    is the last, free line of defense before a refund ships.
    """
    gold = shoplab.rules.decide(ticket, order, customer)
    fields = ("decision", "policy_id", "refund_usd")
    if not isinstance(pred, dict):
        return {"agrees": False, "gold": gold, "pred": pred, "mismatch": list(fields)}
    mismatch = []
    for field in fields:
        if field == "refund_usd":
            if not _amounts_agree(pred.get(field), gold[field]):
                mismatch.append(field)
        elif pred.get(field) != gold[field]:
            mismatch.append(field)
    return {"agrees": not mismatch, "gold": gold, "pred": pred, "mismatch": mismatch}
