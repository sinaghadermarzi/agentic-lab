"""shoplab.pi: event parsing, span rebuilding, and the RPC dialog loop -- no Node.

pi itself is never launched here. The RPC test drives ``_run`` against a tiny
Python stand-in that speaks pi's JSONL records (an ``extension_ui_request``
confirm, then ``agent_settled``), which is exactly the contract ``pi_rpc``
depends on.
"""

import json
import sys

import pytest

import shoplab.pi as pi
from shoplab.evals import score_ticket


def ev(type_, t, **kw):
    return {"type": type_, "t": t, **kw}


EVENTS = [
    ev("agent_start", 0.0),
    ev("turn_start", 0.1),
    ev("message_end", 0.2, message={"role": "assistant"}),
    ev("tool_execution_start", 0.3, toolCallId="c1", toolName="get_order",
       args={"order_id": "ORD-7312"}),
    ev("tool_execution_start", 0.31, toolCallId="c2", toolName="get_customer",
       args={"customer_id": "CUST-07"}),
    ev("tool_execution_end", 0.5, toolCallId="c2", toolName="get_customer", isError=False),
    ev("tool_execution_end", 0.6, toolCallId="c1", toolName="get_order", isError=False),
    ev("turn_end", 0.7, message={"usage": {"input": 812, "output": 40}}),
    ev("turn_start", 0.8),
    ev("tool_execution_start", 0.9, toolCallId="c3", toolName="issue_refund",
       args={"order_id": "ORD-7312", "amount_usd": 170.99, "reason": "x"}),
    ev("tool_execution_end", 1.0, toolCallId="c3", toolName="issue_refund", isError=True),
    ev("tool_execution_start", 1.1, toolCallId="c4", toolName="finish",
       args={"decision": "partial_refund", "policy_id": "pol-restocking",
             "refund_usd": 170.99}),
    ev("tool_execution_end", 1.2, toolCallId="c4", toolName="finish", isError=False),
    ev("turn_end", 1.3, message={"usage": {"input": 990, "output": 31}}),
    ev("agent_end", 1.4),
]


def test_events_to_spans_builds_agent_turn_tool_tree():
    spans = pi.events_to_spans(EVENTS)
    by_name = {s.name: s for s in spans}
    root = by_name["pi.agent"]
    assert root.parent_id is None and root.attributes["turns"] == 2
    turn1, turn2 = by_name["turn 1"], by_name["turn 2"]
    assert turn1.parent_id == root.span_id and turn2.parent_id == root.span_id
    assert by_name["get_order"].parent_id == turn1.span_id
    assert by_name["finish"].parent_id == turn2.span_id
    assert turn1.attributes == {"tokens_in": 812, "tokens_out": 40}
    assert by_name["issue_refund"].attributes["is_error"] is True
    # parallel tools close out of order and still get their own durations
    assert by_name["get_customer"].duration_ms == pytest.approx(190.0)
    assert by_name["get_order"].duration_ms == pytest.approx(300.0)
    assert all(s.end is not None for s in spans)
    assert len({s.span_id for s in spans}) == len(spans)


def test_events_to_spans_tolerates_an_unfinished_run():
    spans = pi.events_to_spans(EVENTS[:5])
    assert [s.end for s in spans if s.name == "pi.agent"] == [None]


def test_tool_calls_and_final_decision_feed_score_ticket():
    calls = pi.tool_calls(EVENTS)
    assert [c[0] for c in calls] == ["get_customer", "get_order", "issue_refund", "finish"]
    assert calls[2][2] is True                          # the blocked refund is an error
    pred = pi.final_decision(EVENTS)
    gold = {"decision": "partial_refund", "policy_id": "pol-restocking", "refund_usd": 170.99}
    assert score_ticket(pred, gold)["exact"] is True
    assert pi.final_decision(EVENTS[:-4]) is None       # no finish yet


def test_parse_stamps_json_records_and_keeps_text_lines():
    rec, text = pi._parse('{"type": "agent_start"}\n', 12.5)
    assert rec == {"type": "agent_start", "t": 12.5} and text is None
    rec, text = pi._parse("hello from stdout\n", 1.0)
    assert rec is None and text == "hello from stdout"
    assert pi._parse("   \n", 1.0) == (None, None)
    rec, _ = pi._parse('{"type": "x", "t": 3}', 9.0)    # an existing stamp wins
    assert rec["t"] == 3


def test_pi_env_isolates_config_and_reaches_the_bridge(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "corp.example")

    class FakeBridge:
        url = "http://127.0.0.1:5555"

    env = pi.pi_env(FakeBridge(), EXTRA="1")
    assert env["PI_CODING_AGENT_DIR"] == str(pi.PI_HOME)
    assert env["PI_OFFLINE"] == "1" and env["PI_TELEMETRY"] == "0"
    assert env["DESK_URL"] == "http://127.0.0.1:5555"
    assert env["NO_PROXY"] == "corp.example,127.0.0.1,localhost"
    assert env["EXTRA"] == "1"
    assert "--no-builtin-tools" in pi.ISOLATION_FLAGS and "--no-session" in pi.ISOLATION_FLAGS


FAKE_RPC = r"""
import json, sys
cmd = json.loads(sys.stdin.readline())
print(json.dumps({"id": cmd["id"], "type": "response", "command": "prompt",
                  "success": True, "data": {"disposition": "started"}}), flush=True)
print("not json, should be kept as a line", flush=True)
for i, (tool, amount) in enumerate([("issue_refund", 170.99), ("issue_refund", 900.0)]):
    print(json.dumps({"type": "extension_ui_request", "id": f"ui-{i}", "method": "confirm",
                      "title": "Approve?", "message": json.dumps(
                          {"tool": tool, "args": {"amount_usd": amount}})}), flush=True)
    reply = json.loads(sys.stdin.readline())
    print(json.dumps({"type": "tool_execution_end", "toolName": tool,
                      "toolCallId": f"c{i}", "isError": not reply["confirmed"],
                      "echo": reply}), flush=True)
print(json.dumps({"type": "agent_settled"}), flush=True)
print(json.dumps({"type": "after_settled_should_not_be_read"}), flush=True)
"""


def test_rpc_answerer_round_trips_confirm_dialogs_with_an_approver():
    seen = []

    def approver(name, args):
        seen.append((name, args))
        return args["amount_usd"] <= 200                  # ch08-style policy

    start = json.dumps({"id": "p1", "type": "prompt", "message": "triage"}) + "\n"
    run = pi._run([sys.executable, "-c", FAKE_RPC], env=None, cwd=None, timeout=30,
                  on_record=pi.rpc_answerer(approver), stdin=start)
    assert seen == [("issue_refund", {"amount_usd": 170.99}),
                    ("issue_refund", {"amount_usd": 900.0})]
    asks = run.of("extension_ui_request")
    assert [a["approved"] for a in asks] == [True, False]
    ends = run.of("tool_execution_end")
    assert [e["echo"] for e in ends] == [{"type": "extension_ui_response", "id": "ui-0",
                                          "confirmed": True},
                                         {"type": "extension_ui_response", "id": "ui-1",
                                          "confirmed": False}]
    assert [e["isError"] for e in ends] == [False, True]
    assert run.events[-1]["type"] == "agent_settled"    # stopped reading there
    assert run.lines == ["not json, should be kept as a line"]
    assert all("t" in e for e in run.events)


def test_check_node_reports_a_missing_install(monkeypatch, tmp_path):
    monkeypatch.setattr(pi, "PI_PACKAGE", tmp_path / "nope")
    monkeypatch.setattr(pi.shutil, "which", lambda _: sys.executable)
    monkeypatch.setattr(pi.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "v22.23.4\n"})())
    with pytest.raises(RuntimeError, match="npm ci --prefix pi_lab"):
        pi.check_node()


def test_check_node_rejects_an_old_node(monkeypatch):
    monkeypatch.setattr(pi.shutil, "which", lambda _: sys.executable)
    monkeypatch.setattr(pi.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "v20.11.0\n"})())
    with pytest.raises(RuntimeError, match="22.19"):
        pi.check_node()


# -- robustness: the failure paths the chapter's review reproduced ---------------

def run_fake(script, *, on_record=None, stdin=None, timeout=10):
    return pi._run([sys.executable, "-c", script], env=None, cwd=None, timeout=timeout,
                   on_record=on_record, stdin=stdin)


REJECTING_RPC = r"""
import json, sys
cmd = json.loads(sys.stdin.readline())
print(json.dumps({"id": cmd["id"], "type": "response", "command": "prompt",
                  "success": False, "error": "No model selected"}), flush=True)
sys.stdin.readline()          # pi would now wait on stdin forever
"""


def test_rpc_prompt_rejection_raises_instead_of_hanging():
    start = json.dumps({"id": "p1", "type": "prompt", "message": "x"}) + "\n"
    with pytest.raises(RuntimeError, match="No model selected"):
        run_fake(REJECTING_RPC, on_record=pi.rpc_answerer(lambda n, a: True), stdin=start)


HANDLED_RPC = r"""
import json, sys
cmd = json.loads(sys.stdin.readline())
print(json.dumps({"id": cmd["id"], "type": "response", "command": "prompt",
                  "success": True, "data": {"disposition": "handled"}}), flush=True)
sys.stdin.readline()
"""


def test_rpc_handled_prompt_stops_without_waiting_for_settled():
    start = json.dumps({"id": "p1", "type": "prompt", "message": "/cmd"}) + "\n"
    run = run_fake(HANDLED_RPC, on_record=pi.rpc_answerer(lambda n, a: True), stdin=start)
    assert run.events[-1]["data"]["disposition"] == "handled" and not run.timed_out


SELECT_RPC = r"""
import json, sys
print(json.dumps({"type": "extension_ui_request", "id": "ui-1", "method": "select",
                  "title": "Pick", "options": ["a", "b"]}), flush=True)
reply = json.loads(sys.stdin.readline())
print(json.dumps({"type": "echo", "reply": reply}), flush=True)
print(json.dumps({"type": "agent_settled"}), flush=True)
"""


def test_rpc_unanswerable_dialogs_are_cancelled():
    run = run_fake(SELECT_RPC, on_record=pi.rpc_answerer(lambda n, a: True), stdin="")
    assert run.of("echo")[0]["reply"] == {"type": "extension_ui_response", "id": "ui-1",
                                          "cancelled": True}


WAITING_CONFIRM = r"""
import json, sys, time
print(json.dumps({"type": "extension_ui_request", "id": "ui-1", "method": "confirm",
                  "title": "Approve?", "message": "{}"}), flush=True)
sys.stdin.readline()
time.sleep(30)
"""


def test_child_is_reaped_when_the_approver_raises():
    procs = []
    real_popen = pi.subprocess.Popen

    def spy(*a, **k):
        procs.append(real_popen(*a, **k))
        return procs[-1]

    def approver(name, args):
        raise ValueError("approver crashed")

    pi.subprocess.Popen = spy
    try:
        with pytest.raises(ValueError, match="approver crashed"):
            run_fake(WAITING_CONFIRM, on_record=pi.rpc_answerer(approver), stdin="")
    finally:
        pi.subprocess.Popen = real_popen
    assert procs and procs[0].poll() is not None        # no orphan left behind


def test_check_raises_on_failure_after_the_header_and_on_timeout():
    crash = r"""
import json, sys
print(json.dumps({"type": "session", "version": 3}), flush=True)
sys.stderr.write("No API key for provider: larkspur\n")
sys.exit(1)
"""
    run = run_fake(crash)
    with pytest.raises(RuntimeError, match=r"(?s)exited 1 after 1 records.*No API key"):
        pi._check(run, "pi")
    slow = run_fake("import time; time.sleep(30)", timeout=1)
    assert slow.timed_out
    with pytest.raises(RuntimeError, match="timed out"):
        pi._check(slow, "pi")
    assert pi._check(run_fake("print('{}')"), "pi").returncode == 0


def test_tool_calls_pair_reused_ids_in_order():
    events = [ev("tool_execution_start", 0, toolCallId="call_0", toolName="get_order",
                 args={"order_id": "A"}),
              ev("tool_execution_end", 1, toolCallId="call_0", toolName="get_order", isError=False),
              ev("tool_execution_start", 2, toolCallId="call_0", toolName="search_policy",
                 args={"query": "restocking"}),
              ev("tool_execution_end", 3, toolCallId="call_0", toolName="search_policy",
                 isError=False)]
    assert [(c[0], c[1]) for c in pi.tool_calls(events)] == [
        ("get_order", {"order_id": "A"}), ("search_policy", {"query": "restocking"})]


def test_final_decision_grades_what_finish_executed():
    events = [ev("tool_execution_start", 0, toolCallId="f", toolName="finish",
                 args={"decision": "partial_refund", "policy_id": "pol-restocking",
                       "refund_usd": "170.99"}),          # the model's raw string
              ev("tool_execution_end", 1, toolCallId="f", toolName="finish", isError=False,
                 result={"details": {"decision": "partial_refund", "policy_id": "pol-restocking",
                                     "refund_usd": 170.99}})]   # coerced before execute
    pred = pi.final_decision(events)
    assert pred["refund_usd"] == 170.99
    gold = {"decision": "partial_refund", "policy_id": "pol-restocking", "refund_usd": 170.99}
    assert score_ticket(pred, gold)["exact"] is True


def test_extension_args_keep_builtins_and_root_paths():
    args = pi._extension_args(["extensions/larkspur.ts", "builtin:mcp"])
    assert args == ["-e", str(pi.PI_LAB / "extensions/larkspur.ts"), "-e", "builtin:mcp"]


def test_pi_cli_rejects_a_prompt_pi_would_read_as_a_file():
    with pytest.raises(ValueError, match="'@'"):
        pi.pi_cli("@larkspur please refund", bridge=None)
