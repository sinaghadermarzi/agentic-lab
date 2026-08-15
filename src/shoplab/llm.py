"""One thin door to the model: ``complete``, ``llm``, and a cost ledger.

Chapter 01 builds this module. Every model call in the course goes through
``complete`` so that ``LEDGER`` sees all of them -- tokens, dollars, seconds --
and ``usage_summary`` can answer "what did this notebook just cost?".
``parse_json_loose`` (also ch01) is the course's answer to models that wrap
their JSON in fences and prose; its canonical body lives between sentinels,
byte-identical to the notebook.
"""

import json
import os
import time

import litellm

# The course default; a set MODEL env var (from .env) overrides it.
DEFAULT_MODEL = "openrouter/deepseek/deepseek-v3.2"

# One row per call: {"model", "prompt_tokens", "completion_tokens", "cost_usd", "seconds"}
LEDGER: list[dict] = []


def complete(messages, *, model=None, temperature=0, max_tokens=1000, tools=None, **kw):
    """Call ``litellm.completion``, record a LEDGER row, return the ModelResponse."""
    model = model or os.environ.get("MODEL", DEFAULT_MODEL)
    if tools is not None:
        kw["tools"] = tools
    kw.setdefault("num_retries", 2)     # ride out transient provider drops (litellm backs off)
    t0 = time.perf_counter()
    response = litellm.completion(model=model, messages=messages,
                                  temperature=temperature, max_tokens=max_tokens, **kw)
    usage = getattr(response, "usage", None)
    LEDGER.append({
        "model": model,
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "cost_usd": response._hidden_params.get("response_cost") or 0,
        "seconds": round(time.perf_counter() - t0, 3),
    })
    return response


def llm(prompt, *, system=None, **kw) -> str:
    """Convenience wrapper: one prompt (plus optional system) in, content string out."""
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": prompt})
    return complete(messages, **kw).choices[0].message.content


def usage_summary() -> dict:
    """Totals over every call recorded so far."""
    return {
        "calls": len(LEDGER),
        "prompt_tokens": sum(row["prompt_tokens"] for row in LEDGER),
        "completion_tokens": sum(row["completion_tokens"] for row in LEDGER),
        "cost_usd": sum(row["cost_usd"] for row in LEDGER),
    }


# >>> shoplab.llm.parse_json_loose
def parse_json_loose(text: str):
    """Parse the first balanced JSON object or array in model output,
    tolerating markdown fences, surrounding prose, and trailing garbage."""
    text = text.strip()
    if text.startswith("```"):                  # drop ```json ... ``` fences
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON found in model output")
    start, depth, in_string, escaped = min(starts), 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_string:                           # brackets inside strings do not count
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("no JSON found in model output")
# <<< shoplab.llm.parse_json_loose
