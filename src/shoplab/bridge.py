"""The desk bridge: the course's model door and tool door, served over HTTP.

Chapter 19 builds this module so a harness written in another language -- pi,
in TypeScript -- can run the Larkspur desk without moving the course's seams.
One small stdlib HTTP server, started on a background thread, exposes:

- ``POST /v1/chat/completions`` -- an OpenAI-compatible endpoint backed by
  ``shoplab.llm.complete``. Every call a foreign harness makes therefore still
  lands in ``shoplab.llm.LEDGER`` and in the litellm disk cache, so cached
  reruns stay free. A streaming request gets the finished message re-emitted
  as Server-Sent-Event chunks by ``sse_chunks`` (the chapter's sentinel region,
  byte-identical to the notebook).
- ``GET /tools`` -- the desk's toolset as data: name, description, JSON-schema
  params, and the ``risky`` flag (``shoplab.tools.Tool`` minus its ``fn``).
- ``POST /tools/<name>`` -- runs one tool through ``shoplab.tools.run_tool``:
  the response body is always the JSON string ``run_tool`` returns, never an
  HTTP error, which is chapter 02's errors-as-results contract kept intact
  across the process boundary. Tool calls are serialized under a lock so a
  harness that runs tools in parallel cannot interleave writes to the Ledger.

``DeskBridge`` is a context manager (``with DeskBridge(tools) as bridge:``)
that also exposes ``start``/``stop`` for notebooks that keep one bridge alive
across cells, and records every request it served in ``bridge.calls``.
"""

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import shoplab.llm
from shoplab.tools import run_tool


# >>> shoplab.bridge.sse_chunks
def sse_chunks(msg, *, model, usage=None, finish_reason=None, chunk_id="chatcmpl-desk"):
    """Re-emit one finished chat message as the OpenAI streaming chunk sequence:
    the text delta, one delta per tool call (keyed by index), a finish chunk
    carrying finish_reason and usage, then the literal [DONE] sentinel."""
    def chunk(delta, finish=None, **extra):
        return {"id": chunk_id, "object": "chat.completion.chunk", "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                **extra}
    calls = msg.get("tool_calls") or []
    out = [chunk({"role": "assistant", "content": msg.get("content") or ""})]
    for i, tc in enumerate(calls):
        out.append(chunk({"tool_calls": [{
            "index": i, "id": tc["id"], "type": "function",
            "function": {"name": tc["function"]["name"],
                         "arguments": tc["function"].get("arguments") or "{}"}}]}))
    finish = finish_reason or ("tool_calls" if calls else "stop")
    out.append(chunk({}, finish, **({"usage": usage} if usage else {})))
    return [f"data: {json.dumps(c)}\n\n" for c in out] + ["data: [DONE]\n\n"]
# <<< shoplab.bridge.sse_chunks


def _text(content):
    """OpenAI content may be a string or a list of parts; litellm and the cache
    key both want one plain string, so text parts are joined and others dropped."""
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content
                       if isinstance(p, dict) and p.get("type") == "text")
    return content


def normalize_messages(messages):
    """Map a foreign client's chat messages onto the plain shape the course sends:
    ``developer`` becomes ``system``, content parts become one string, and only
    the fields litellm needs survive (no vendor extras that would perturb the
    cache key)."""
    out = []
    for m in messages:
        role = "system" if m.get("role") == "developer" else m.get("role")
        row = {"role": role, "content": _text(m.get("content"))}
        if m.get("tool_calls"):
            row["tool_calls"] = [{"id": tc["id"], "type": "function",
                                  "function": {"name": tc["function"]["name"],
                                               "arguments": tc["function"].get("arguments") or "{}"}}
                                 for tc in m["tool_calls"]]
        if role == "tool":
            row["tool_call_id"] = m.get("tool_call_id")
        if row["content"] is None and role != "assistant":
            row["content"] = ""
        out.append(row)
    return out


def _message_dict(msg):
    """A litellm Message (or a test fake) as a plain dict with content/tool_calls."""
    if hasattr(msg, "model_dump"):
        return msg.model_dump(exclude_none=True)
    calls = [{"id": tc.id, "type": "function",
              "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
             for tc in (getattr(msg, "tool_calls", None) or [])]
    return {"role": "assistant", "content": getattr(msg, "content", None),
            **({"tool_calls": calls} if calls else {})}


def _finish_reason(msg, upstream):
    """The finish_reason to report: the upstream one when it is a standard value,
    except that a message carrying tool calls always reports ``tool_calls``
    unless it was truncated (``length``). Some providers say ``stop`` on a
    tool-call turn; a strict client would then never run the tools."""
    calls = bool(msg.get("tool_calls"))
    if upstream == "length":
        return "length"
    if calls:
        return "tool_calls"
    return upstream if upstream in ("stop", "content_filter") else "stop"


def _usage(response):
    u = getattr(response, "usage", None)
    prompt = getattr(u, "prompt_tokens", 0) or 0
    completion = getattr(u, "completion_tokens", 0) or 0
    return {"prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": prompt + completion}


class DeskBridge:
    """Serve the desk's model door and tool door on ``http://127.0.0.1:<port>``.

    ``tools`` is a ``standard_tools()``-style dict; ``model`` is the LiteLLM
    string every model call is routed to (default: ``shoplab.llm``'s MODEL
    resolution). ``max_tokens`` is fixed per bridge rather than taken from the
    client, so the litellm cache key does not depend on the harness's defaults.
    """

    def __init__(self, tools, *, model=None, host="127.0.0.1", port=0, max_tokens=1000):
        self.tools, self.model, self.max_tokens = tools, model, max_tokens
        self.calls: list[dict] = []
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer((host, port), self._handler())
        self._server.daemon_threads = True
        self._thread = None

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._server.serve_forever,
                                            name="desk-bridge", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=5)
            self._thread = None
        self._server.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # -- the two doors ------------------------------------------------------

    def chat(self, body: dict):
        """Answer one chat-completions request; returns (message_dict, response)."""
        tools = body.get("tools") or None          # pi sends tools=[] on tool-free history
        r = shoplab.llm.complete(normalize_messages(body.get("messages") or []),
                                 model=self.model, tools=tools, max_tokens=self.max_tokens)
        choice = r.choices[0]
        msg = _message_dict(choice.message)
        for i, tc in enumerate(msg.get("tool_calls") or []):
            tc["id"] = tc.get("id") or f"call_{i}"   # pi keys replays on the id: never empty
        self.calls.append({"door": "model", "t": time.time(),
                           "tool_calls": [tc["function"]["name"] for tc in msg.get("tool_calls") or []],
                           "cost_usd": shoplab.llm.LEDGER[-1]["cost_usd"] if shoplab.llm.LEDGER else 0})
        return msg, r

    def catalog(self) -> list:
        return [{"name": t.name, "description": t.description, "parameters": t.params,
                 "risky": t.risky} for t in self.tools.values()]

    def call_tool(self, name: str, args: dict) -> str:
        with self._lock:
            result = run_tool(self.tools, name, args)
        try:
            parsed = json.loads(result)
        except ValueError:
            parsed = None
        self.calls.append({"door": "tool", "t": time.time(), "name": name, "args": args,
                           "error": isinstance(parsed, dict) and "error" in parsed})
        return result

    # -- HTTP plumbing --------------------------------------------------------

    def _handler(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):        # keep the notebook output clean
                pass

            def _send(self, status, body: bytes, ctype="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json_body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")

            def do_GET(self):
                if self.path.rstrip("/") == "/tools":
                    return self._send(200, json.dumps(bridge.catalog()).encode())
                if self.path.rstrip("/") == "/v1/models":
                    data = [{"id": "larkspur-desk", "object": "model", "owned_by": "agentic-lab"}]
                    return self._send(200, json.dumps({"object": "list", "data": data}).encode())
                self._send(404, b'{"error": {"message": "not found"}}')

            def do_POST(self):
                try:
                    body = self._json_body()
                except ValueError:
                    return self._send(400, b'{"error": {"message": "body is not JSON"}}')
                if self.path.startswith("/tools/"):
                    name = self.path[len("/tools/"):]
                    args = body if isinstance(body, dict) else {}
                    return self._send(200, bridge.call_tool(name, args).encode())
                if self.path.rstrip("/") != "/v1/chat/completions":
                    return self._send(404, b'{"error": {"message": "not found"}}')
                try:
                    msg, r = bridge.chat(body)
                except Exception as exc:          # upstream failure -> an OpenAI-style error
                    err = {"error": {"message": f"{type(exc).__name__}: {exc}"[:500],
                                     "type": "upstream_error"}}
                    return self._send(502, json.dumps(err).encode())
                model = body.get("model") or "larkspur-desk"
                finish = _finish_reason(msg, getattr(r.choices[0], "finish_reason", None))
                rid = "chatcmpl-" + uuid.uuid4().hex[:12]
                if body.get("stream"):
                    frames = sse_chunks(msg, model=model, usage=_usage(r),
                                        finish_reason=finish, chunk_id=rid)
                    return self._send(200, "".join(frames).encode(), "text/event-stream")
                full = {"id": rid, "object": "chat.completion", "model": model,
                        "choices": [{"index": 0, "message": {"role": "assistant", **msg},
                                     "finish_reason": finish}],
                        "usage": _usage(r)}
                self._send(200, json.dumps(full).encode())

        return Handler
