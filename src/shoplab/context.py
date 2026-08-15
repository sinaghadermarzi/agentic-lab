"""Managing the one resource an agent silently burns: its context window.

Chapter 10 builds this module -- the machinery for watching a message list grow,
moving bulk out of the window, compacting the middle of a long run, and running a
sub-agent as a context firewall. ``count_tokens`` is the honest measuring tape
(``litellm.token_counter``, offline); ``ContextLedger`` records the growth curve;
``offload``/``load_offload`` swap a big blob for a small handle; ``compact`` folds
the middle of a conversation into one summary line (its canonical body lives
between sentinels, byte-identical to the notebook); and ``run_subagent`` runs a
fresh loop and returns only its answer, so the parent never sees the sub-agent's
intermediate turns.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import litellm

import shoplab.llm
import shoplab.loop


def count_tokens(messages, *, model=None) -> int:
    """Token count of a message list under a model's tokenizer.

    Tolerates a bare string (wrapped as one user message). ``model`` defaults to
    the ``MODEL`` env var, then the course default. Offline: no network call."""
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    model = model or os.environ.get("MODEL", shoplab.llm.DEFAULT_MODEL)
    return litellm.token_counter(model=model, messages=messages)


@dataclass
class ContextLedger:
    """A running record of how a conversation's token footprint grows.

    Call ``observe`` once per step with the current message list; ``growth``
    hands back the rows (ready for a DataFrame) and ``peak`` the high-water mark."""
    model: str | None = None
    steps: list[dict] = field(default_factory=list)

    def observe(self, messages, *, label="") -> int:
        """Record and return the token count of ``messages`` at this step."""
        tokens = count_tokens(messages, model=self.model)
        self.steps.append({"label": label, "messages": len(messages),
                           "tokens": tokens, "step": len(self.steps)})
        return tokens

    def growth(self) -> list[dict]:
        """The recorded rows, in order -- convenience for a DataFrame."""
        return self.steps

    def peak(self) -> int:
        """The largest token count observed so far (0 if nothing observed)."""
        return max((row["tokens"] for row in self.steps), default=0)


def offload(content: str, *, tag="blob", dir="artifacts/offload") -> dict:
    """Write a big blob to ``<dir>/<tag>-<n>.txt`` and return a small handle.

    ``n`` is the count of existing ``<tag>-*.txt`` files, so numbering is
    deterministic (no random, no timestamps). The handle
    ``{"ref", "chars", "preview"}`` is what stays in the agent's context in place
    of the content; ``load_offload`` fetches the full text back on demand."""
    d = Path(dir)
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob(f"{tag}-*.txt")))
    path = d / f"{tag}-{n}.txt"
    path.write_text(content, encoding="utf-8")
    return {"ref": str(path), "chars": len(content), "preview": content[:120]}


def load_offload(handle) -> str:
    """Read back an offloaded blob. Accepts the handle dict or its ref string."""
    ref = handle["ref"] if isinstance(handle, dict) else handle
    path = Path(ref)
    if not path.exists():
        raise FileNotFoundError(f"no offload at {ref} -- nothing to load")
    return path.read_text(encoding="utf-8")


def _default_summary(messages) -> str:
    """A cheap, deterministic stand-in summary: roles plus a snippet of each turn.

    No LLM needed, so ``compact`` is testable offline; pass your own ``summarizer``
    to ``compact`` for a real model-written summary."""
    return " | ".join(f"{m.get('role', '?')}: {str(m.get('content') or '')[:80]}"
                      for m in messages)


# >>> shoplab.context.compact
def compact(messages, *, keep_last=4, summarizer=None) -> list:
    """Fold the middle of a conversation into one summary line.

    Keep the leading system message(s) at the head and the last ``keep_last``
    messages verbatim; replace everything between with a single
    ``{"role": "system", "content": "[compacted N messages] " + summary}``.
    ``summarizer(list)->str`` defaults to a deterministic role+snippet join (no
    LLM, so this is testable offline). Never orphan a trailing tool result from
    its assistant tool_call: if the cut would sever one, the kept window extends
    to keep them together. Returns a NEW list."""
    summarizer = summarizer or _default_summary
    head = 0
    while head < len(messages) and messages[head].get("role") == "system":
        head += 1
    system_head, body = messages[:head], messages[head:]
    cut = max(0, len(body) - keep_last)
    while 0 < cut < len(body) and body[cut].get("role") == "tool":
        cut -= 1  # would orphan a tool result from its assistant tool_call
    middle, tail = body[:cut], body[cut:]
    if not middle:
        return list(messages)
    note = {"role": "system",
            "content": f"[compacted {len(middle)} messages] " + summarizer(middle)}
    return system_head + [note] + tail
# <<< shoplab.context.compact


def run_subagent(task, tools, *, model=None, max_steps=6, system=None) -> dict:
    """Run a fresh agent loop and return only its compact result.

    The sub-agent runs ``shoplab.loop.run_agent`` in a brand-new message list; the
    caller gets back only ``{"answer", "steps", "stop_reason"}``, so the parent
    context never sees the sub-agent's intermediate turns. This is the
    "sub-agent = context firewall" primitive of chapters 10 and 11."""
    result = shoplab.loop.run_agent(task, tools, model=model,
                                    max_steps=max_steps, system=system)
    return {"answer": result.answer, "steps": result.steps,
            "stop_reason": result.stop_reason}
