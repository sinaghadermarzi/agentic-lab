"""Guardrails for the ops-desk agent: budgets, checkpoints, and approval gates.

Chapter 08 builds this module -- the machinery that keeps an autonomous loop from
spending too much, losing its place, or moving money unsupervised. ``Budget`` caps
a run by call count and dollars and is meant to hang off the loop's ``on_step``
hook; ``Checkpoint`` saves and restores agent state so a crashed run can resume;
``require_approval`` wraps a risky ``shoplab.tools.Tool`` in a human-in-the-loop
gate. ``Budget`` and ``Checkpoint.save`` are the chapter's sentinel regions
(byte-identical to the notebook).
"""

import json
from dataclasses import dataclass
from pathlib import Path

from shoplab.tools import Tool


class BudgetExceeded(Exception):
    """Raised by ``Budget.charge`` the moment a call or cost ceiling is crossed."""


# >>> shoplab.controls.Budget
@dataclass
class Budget:
    """A running tally of calls and dollars with optional ceilings; ``charge``
    raises ``BudgetExceeded`` the instant either is crossed. Drive it from the loop
    ``on_step`` hook: ``budget.charge(shoplab.llm.LEDGER[-1]["cost_usd"])``."""
    max_calls: int | None = None
    max_cost_usd: float | None = None
    calls: int = 0
    cost_usd: float = 0.0
    def charge(self, cost=0.0):
        self.calls += 1
        self.cost_usd += cost or 0.0
        if self.max_calls is not None and self.calls > self.max_calls:
            raise BudgetExceeded(f"call budget spent: {self.calls} > {self.max_calls}")
        if self.max_cost_usd is not None and self.cost_usd > self.max_cost_usd:
            raise BudgetExceeded(f"cost budget spent: {self.cost_usd:.6f} > {self.max_cost_usd:.6f}")
        return self
    @property
    def remaining_calls(self):
        return None if self.max_calls is None else self.max_calls - self.calls
    @property
    def remaining_cost(self):
        return None if self.max_cost_usd is None else round(self.max_cost_usd - self.cost_usd, 6)
    def snapshot(self) -> dict:
        return {"calls": self.calls, "cost_usd": round(self.cost_usd, 6),
                "remaining_calls": self.remaining_calls, "remaining_cost": self.remaining_cost}
# <<< shoplab.controls.Budget


class Checkpoint:
    """Save and restore agent state as JSON so a run can resume after a crash.

    State is the small dict ``{"messages", "step", "meta"}``: the running message
    list, the step reached, and any bookkeeping. ``save`` writes it atomically and
    ``load`` reads it back with a clear error when the file is missing.
    """

    # >>> shoplab.controls.Checkpoint.save
    @staticmethod
    def save(state: dict, path) -> Path:
        """Atomically write ``{messages, step, meta}`` as JSON; return the Path.

        Dumps to a sibling ``.tmp`` then ``replace``s it into place, so a reader
        never sees a half-written file even if the process dies mid-write."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"messages": state.get("messages", []),
                   "step": state.get("step", 0), "meta": state.get("meta", {})}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path
    # <<< shoplab.controls.Checkpoint.save

    @staticmethod
    def load(path) -> dict:
        """Load a checkpoint written by ``save``; a clear error if it is missing."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"no checkpoint at {path} -- nothing to resume from")
        return json.loads(path.read_text(encoding="utf-8"))


def require_approval(tool: Tool, approver) -> Tool:
    """Wrap a risky tool in a human-in-the-loop gate.

    Returns a NEW ``shoplab.tools.Tool`` with the same name, description, params,
    and ``risky`` flag; its ``fn`` first calls ``approver(tool.name, kwargs)``. If
    the approver returns a falsy value (``False`` or ``None``) the underlying fn is
    never called and the gate returns ``{"blocked": True, "reason": "approval
    denied"}``; otherwise it runs the real tool and returns its result. ``approver``
    signature: ``(name: str, args: dict) -> bool``.
    """
    def gated(**kwargs):
        if not approver(tool.name, kwargs):
            return {"blocked": True, "reason": "approval denied"}
        return tool.fn(**kwargs)

    return Tool(tool.name, tool.description, tool.params, gated, risky=tool.risky)


def console_approver(name: str, args: dict) -> bool:
    """Interactive approver for a terminal: show the pending call, read a y/n.

    Notebooks pass their own lambda (an auto-approver) instead of blocking on
    ``input()``; this is the default for a human sitting at a console.
    """
    print(f"approve {name}({args})? [y/N] ", end="")
    return input().strip().lower() in ("y", "yes")
