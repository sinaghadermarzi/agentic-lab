"""Drive pi (TypeScript) from Python, and read back what it did.

Chapter 19's Python half. pi runs as a Node subprocess against a running
``shoplab.bridge.DeskBridge``; this module

- finds the course's Node project (``PI_LAB``) and checks it is installed
  (``check_node``),
- runs one ``pi_lab/*.ts`` script with Node's built-in type stripping
  (``run_ts``) or the pi CLI in JSON mode with the course's isolation flags
  (``pi_cli``), streaming stdout and stamping each JSONL record with the time
  it arrived (``PiRun.events``),
- drives the CLI's RPC mode with a chapter-08-style ``approver(name, args)``
  answering the extension's confirm dialogs (``pi_rpc``),
- and turns pi's event stream into data earlier chapters already read:
  ``final_decision`` pulls the ``finish`` tool's arguments out for
  ``shoplab.evals.score_ticket`` (ch04), and ``events_to_spans`` (the
  sentinel region, byte-identical to the notebook) rebuilds chapter 03's
  ``Span`` tree from pi's agent / turn / tool events.

Isolation: every subprocess gets ``PI_CODING_AGENT_DIR=artifacts/pi-agent`` so
pi never reads or writes the learner's ``~/.pi``, ``PI_OFFLINE=1`` (no model
catalog refresh), ``PI_SKIP_VERSION_CHECK=1``, ``PI_TELEMETRY=0``, and a
``NO_PROXY`` covering the loopback bridge.
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from shoplab.trace import Span

ROOT = Path(__file__).resolve().parents[2]
PI_LAB = ROOT / "pi_lab"
PI_HOME = ROOT / "artifacts" / "pi-agent"          # pi's config dir, never ~/.pi
PI_PACKAGE = PI_LAB / "node_modules" / "@earendil-works" / "pi-coding-agent"
MIN_NODE = (22, 19, 0)
DESK_MODEL = "larkspur/larkspur-desk"          # registered by pi_lab/extensions/larkspur.ts

# The CLI flags that make a pi run see only what this chapter hands it: no
# session file, no discovered extensions/skills/templates/themes/context files,
# no built-in tools (no bash/edit/write), no MCP, no project trust, no network
# beyond the bridge. Explicit -e extensions still load under --no-extensions.
ISOLATION_FLAGS = ["--offline", "--no-session", "--no-extensions", "--no-builtin-tools",
                   "--no-context-files", "--no-skills", "--no-prompt-templates",
                   "--no-themes", "--no-mcp", "--no-approve"]


@dataclass
class PiRun:
    """One finished pi subprocess: parsed JSONL ``events`` (each with an arrival
    stamp ``t``), any non-JSON stdout ``lines``, ``stderr``, ``returncode``, and
    whether the watchdog had to kill it (``timed_out``)."""
    events: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    stderr: str = ""
    returncode: int | None = None
    timed_out: bool = False

    def of(self, *types):
        return [e for e in self.events if e.get("type") in types]


def _version(text):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def check_node() -> str:
    """Return the Node version string, or raise with the exact fix to run."""
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node not found: install Node.js >= 22.19 (https://nodejs.org)")
    ver = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    if _version(ver) < MIN_NODE:
        raise RuntimeError(f"node {ver} is too old: pi 1.4 needs >= 22.19")
    if not PI_PACKAGE.exists():
        raise RuntimeError("pi_lab is not installed: run `npm ci --prefix pi_lab` once")
    return ver


def pi_env(bridge=None, **extra) -> dict:
    """The environment every pi subprocess runs with (see module docstring)."""
    env = os.environ.copy()
    loopback = "127.0.0.1,localhost"
    for key in ("NO_PROXY", "no_proxy"):
        env[key] = ",".join(x for x in (env.get(key), loopback) if x)
    env.update({"PI_CODING_AGENT_DIR": str(PI_HOME), "PI_OFFLINE": "1",
                "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0"})
    if bridge is not None:
        env["DESK_URL"] = bridge.url
    env.update({k: str(v) for k, v in extra.items()})
    return env


def pi_bin() -> list:
    """The pi CLI as an argv prefix: ``node <cli.js>`` from the pinned package
    (portable -- no reliance on a ``node_modules/.bin`` shim)."""
    pkg = json.loads((PI_PACKAGE / "package.json").read_text(encoding="utf-8"))
    bin_field = pkg["bin"]
    rel = bin_field if isinstance(bin_field, str) else bin_field["pi"]
    return ["node", str(PI_PACKAGE / rel)]


def _parse(line, stamp):
    line = line.rstrip("\r\n")
    if not line.strip():
        return None, None
    try:
        rec = json.loads(line)
    except ValueError:
        return None, line
    if isinstance(rec, dict):
        rec.setdefault("t", stamp)
        return rec, None
    return None, line


def _drain(stream, sink):
    sink.append(stream.read())


def _run(cmd, *, env, cwd, timeout, on_record=None, stdin=None):
    """Run cmd, read stdout line by line (stamping arrivals), return a PiRun.

    ``on_record(rec, proc)`` sees each JSON record as it arrives (RPC mode
    answers dialogs from it); returning True stops reading and ends the run."""
    run = PiRun()
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, text=True, encoding="utf-8",
                            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    err_sink = []
    err_thread = threading.Thread(target=_drain, args=(proc.stderr, err_sink), daemon=True)
    err_thread.start()

    def watchdog():
        run.timed_out = True
        proc.kill()

    timer = threading.Timer(timeout, watchdog)
    timer.start()
    try:
        if stdin is not None:
            proc.stdin.write(stdin)
            proc.stdin.flush()
        for line in iter(proc.stdout.readline, ""):
            rec, text = _parse(line, time.time())
            if text is not None:
                run.lines.append(text)
            if rec is None:
                continue
            run.events.append(rec)
            if on_record is not None and on_record(rec, proc):
                break
    finally:
        # Normal end, an approver that raises, a broken pipe, a notebook
        # interrupt: every path closes stdin (pi's cue to shut down) and reaps
        # the child, so no pi process outlives the cell.
        timer.cancel()
        if proc.stdin:
            try:
                proc.stdin.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    err_thread.join(timeout=5)
    run.stderr, run.returncode = "".join(err_sink), proc.returncode
    return run


def _check(run, what):
    """Raise, with pi's stderr, unless the process ended cleanly. (JSON mode
    prints a session header first, so "some records arrived" proves nothing;
    a model turn that errors still exits 0 and shows up in the events.)"""
    if run.timed_out:
        raise RuntimeError(f"{what} timed out after {len(run.events)} records:\n{run.stderr[-1500:]}")
    if run.returncode not in (0, None):
        raise RuntimeError(f"{what} exited {run.returncode} after {len(run.events)} records:\n"
                           f"{run.stderr[-1500:]}")
    return run


def _extension_args(extensions) -> list:
    """``-e`` flags: ``builtin:<name>`` passes through, anything else is a path
    under ``pi_lab/``."""
    out = []
    for ext in extensions:
        ext = str(ext)
        out += ["-e", ext if ext.startswith("builtin:") else str(PI_LAB / ext)]
    return out


def run_ts(script, *args, bridge, timeout=180, **env) -> PiRun:
    """Run ``pi_lab/<script>`` (TypeScript, via Node's type stripping)."""
    check_node()
    cmd = ["node", "--no-warnings", str(PI_LAB / script), *map(str, args)]
    return _check(_run(cmd, env=pi_env(bridge, **env), cwd=PI_LAB, timeout=timeout), script)


def pi_cli(prompt, *, bridge, extensions=("extensions/larkspur.ts",), model=DESK_MODEL,
           flags=ISOLATION_FLAGS, extra=(), timeout=240, **env) -> PiRun:
    """One prompt through the pi CLI in JSON mode: a JSONL event per line."""
    if prompt.startswith("@"):     # pi reads a leading @ as a file, even after --
        raise ValueError("pi treats a prompt starting with '@' as a file argument; reword it")
    check_node()
    cmd = [*pi_bin(), "--mode", "json", *flags, "--model", model,
           *_extension_args(extensions), *extra, "--", prompt]
    return _check(_run(cmd, env=pi_env(bridge, **env), cwd=PI_LAB, timeout=timeout), "pi")


def pi_rpc(prompt, *, bridge, approver, extensions=("extensions/larkspur.ts",),
           model=DESK_MODEL, flags=ISOLATION_FLAGS, extra=(), timeout=240, **env) -> PiRun:
    """One prompt through pi's RPC mode; ``approver(name, args) -> bool`` answers
    every ``confirm`` dialog the extension raises (chapter 08's approver contract,
    now on the far side of a process boundary). Ends at ``agent_settled``."""
    check_node()
    cmd = [*pi_bin(), "--mode", "rpc", *flags, "--model", model,
           *_extension_args(extensions), *extra]
    start = json.dumps({"id": "p1", "type": "prompt", "message": prompt}) + "\n"
    return _check(_run(cmd, env=pi_env(bridge, **env), cwd=PI_LAB, timeout=timeout,
                       on_record=rpc_answerer(approver), stdin=start), "pi --mode rpc")


def rpc_answerer(approver):
    """The RPC client's half of the extension-UI subprotocol: answer each
    ``confirm`` request with ``approver(tool, args)`` (the extension sends
    ``{"tool", "args"}`` as the dialog message), mark the record with the
    verdict, cancel dialogs it cannot answer (select / input / editor), and stop
    reading at ``agent_settled`` -- or at once if pi rejected the prompt or
    handled it without starting a run (then no ``agent_settled`` will come)."""
    def reply(proc, payload):
        proc.stdin.write(json.dumps({"type": "extension_ui_response", **payload}) + "\n")
        proc.stdin.flush()

    def answer(rec, proc):
        kind = rec.get("type")
        if kind == "response" and rec.get("command") == "prompt":
            if not rec.get("success"):
                raise RuntimeError(f"pi rejected the prompt: {rec.get('error')}")
            return (rec.get("data") or {}).get("disposition") == "handled"
        if kind == "extension_ui_request" and rec.get("method") == "confirm":
            try:
                ask = json.loads(rec.get("message") or "{}")
            except ValueError:
                ask = {}
            ok = bool(approver(ask.get("tool", rec.get("title", "")), ask.get("args", {})))
            rec["approved"] = ok
            reply(proc, {"id": rec["id"], "confirmed": ok})
        elif kind == "extension_ui_request" and rec.get("method") in ("select", "input", "editor"):
            reply(proc, {"id": rec["id"], "cancelled": True})
        return kind == "agent_settled"
    return answer


def tool_calls(events) -> list:
    """``(name, args, is_error, result)`` for every finished tool execution, in
    completion order. Each end pairs with the earliest still-open start of the
    same id, so an id a provider reuses across turns cannot cross the wires."""
    pending, out = {}, []
    for e in events:
        if e.get("type") == "tool_execution_start":
            pending.setdefault(e.get("toolCallId"), []).append(e)
        elif e.get("type") == "tool_execution_end":
            queue = pending.get(e.get("toolCallId")) or [{}]
            s = queue.pop(0)
            out.append((e.get("toolName") or s.get("toolName"), s.get("args"),
                        bool(e.get("isError")), e.get("result")))
    return out


def final_decision(events):
    """The last successful ``finish`` call as it actually ran -- the dict
    ``score_ticket`` grades -- or None when the run never finished.

    pi validates (and coerces: ``"170.99"`` -> ``170.99``) arguments before
    ``execute``, and the desk's ``finish`` echoes what it received, so the
    result's ``details`` is what ran; the model's raw arguments are the
    fallback."""
    done = []
    for name, args, err, result in tool_calls(events):
        if name == "finish" and not err:
            details = result.get("details") if isinstance(result, dict) else None
            done.append(details if isinstance(details, dict) else args)
    return done[-1] if done else None


# >>> shoplab.pi.events_to_spans
def events_to_spans(events):
    """Rebuild chapter 03's Span tree from pi's events: one span per agent run,
    a child per turn, a grandchild per tool execution, timed by arrival stamps."""
    spans, open_, turns = [], {}, 0
    def begin(key, name, kind, parent_key, t, **attrs):
        parent = open_.get(parent_key)
        s = Span(name, kind, t, None, attrs, f"{len(spans) + 1:016x}",
                 parent.span_id if parent else None)
        spans.append(s)
        open_[key] = s
    def close(key, t, **attrs):
        s = open_.pop(key, None)
        if s is not None:
            s.end = t
            s.attributes.update(attrs)
    for e in events:
        kind, t = e.get("type"), e.get("t", 0.0)
        if kind == "agent_start":
            begin("agent", "pi.agent", "agent", None, t)
        elif kind == "turn_start":
            turns += 1
            begin("turn", f"turn {turns}", "llm", "agent", t)
        elif kind == "tool_execution_start":
            begin(e.get("toolCallId"), e.get("toolName"), "tool", "turn", t)
        elif kind == "tool_execution_end":
            close(e.get("toolCallId"), t, is_error=bool(e.get("isError")))
        elif kind == "turn_end":
            usage = (e.get("message") or {}).get("usage") or {}
            close("turn", t, tokens_in=usage.get("input"), tokens_out=usage.get("output"))
        elif kind == "agent_end":
            close("agent", t, turns=turns)
    return spans
# <<< shoplab.pi.events_to_spans
