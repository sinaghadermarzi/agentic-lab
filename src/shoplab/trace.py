"""Hand-rolled tracing for the ops-desk agent: spans, trees, and OTLP export.

Chapter 03 builds this in-notebook to demystify what observability platforms
actually record. A span is a named, timed node with a parent pointer; a trace
is just the list of spans; OTLP is the envelope that ships them over HTTP.
``Tracer`` collects spans through a context manager (nesting tracked with a
plain stack), ``to_otlp`` converts a span list to the readable OTLP/JSON
mapping, and ``export_phoenix`` posts that payload -- re-encoded as the binary
protobuf Phoenix's collector accepts -- to a local Phoenix server. The
``Span`` dataclass is the chapter's sentinel region (byte-identical to the
notebook).
"""

import base64
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps

import httpx


# >>> shoplab.trace.Span
@dataclass
class Span:
    """One timed operation: a node in the trace tree."""
    name: str
    kind: str
    start: float
    end: float | None
    attributes: dict
    span_id: str
    parent_id: str | None

    @property
    def duration_ms(self):
        return None if self.end is None else round((self.end - self.start) * 1000, 3)
# <<< shoplab.trace.Span


class Tracer:
    """Collects ``Span`` objects; the currently-open span is the next parent."""

    def __init__(self):
        self.spans: list[Span] = []
        self._stack: list[Span] = []

    @contextmanager
    def span(self, name, kind="span", **attrs):
        """Open a span around a block; nested blocks become child spans."""
        s = Span(name=name, kind=kind, start=time.time(), end=None,
                 attributes=dict(attrs), span_id=uuid.uuid4().hex[:16],
                 parent_id=self._stack[-1].span_id if self._stack else None)
        self.spans.append(s)
        self._stack.append(s)
        try:
            yield s
        finally:
            s.end = time.time()
            self._stack.pop()

    def traced(self, name=None, kind="span"):
        """Decorator form of ``span``: one span per call, named after the function."""
        if callable(name):                      # bare @tracer.traced, no parentheses
            return self.traced()(name)

        def decorate(fn):
            @wraps(fn)
            def wrapper(*args, **kwargs):
                with self.span(name or fn.__name__, kind=kind):
                    return fn(*args, **kwargs)
            return wrapper
        return decorate

    def print_tree(self):
        """One line per span, indented by depth: name, kind, duration, attributes."""
        depths = {}
        for s in self.spans:
            depth = depths[s.span_id] = depths.get(s.parent_id, -1) + 1
            duration = "..." if s.duration_ms is None else f"{s.duration_ms:.1f} ms"
            attrs = "  ".join(f"{k}={v!r}" for k, v in s.attributes.items())
            print("  " * depth + f"{s.name}  [{s.kind}]  {duration}"
                  + (f"  {attrs}" if attrs else ""))

    def clear(self):
        """Drop all recorded spans and any open nesting state."""
        self.spans.clear()
        self._stack.clear()


def _ns(seconds):
    """Unix seconds -> the stringified nanoseconds OTLP/JSON expects."""
    return str(int(seconds * 1_000_000_000))


def _attr(key, value):
    return {"key": key, "value": {"stringValue": str(value)}}


def to_otlp(spans, project="agentic-lab"):
    """Convert a span list to an OTLP/JSON payload any collector accepts."""
    trace_id = uuid.uuid4().hex                 # one trace per export, 32 hex chars
    otlp_spans = [{
        "traceId": trace_id,
        "spanId": s.span_id,
        "parentSpanId": s.parent_id or "",
        "name": s.name,
        "kind": 1,                              # SPAN_KIND_INTERNAL
        "startTimeUnixNano": _ns(s.start),
        "endTimeUnixNano": _ns(s.end if s.end is not None else s.start),
        "attributes": [_attr("openinference.span.kind", s.kind.upper())]
                      + [_attr(k, v) for k, v in s.attributes.items()],
    } for s in spans]
    return {"resourceSpans": [{
        "resource": {"attributes": [_attr("openinference.project.name", project)]},
        "scopeSpans": [{"scope": {"name": "shoplab.trace"}, "spans": otlp_spans}],
    }]}


def _to_protobuf(payload) -> bytes:
    """OTLP/JSON -> the binary protobuf encoding Phoenix's collector accepts.

    Same tree, different encoding. The one wrinkle: OTLP/JSON spells the ids
    in hex, while the protobuf JSON parser expects base64-coded bytes."""
    from google.protobuf.json_format import Parse
    from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

    payload = json.loads(json.dumps(payload))               # deep copy
    for rs in payload["resourceSpans"]:
        for ss in rs["scopeSpans"]:
            for span in ss["spans"]:
                for key in ("traceId", "spanId", "parentSpanId"):
                    span[key] = base64.b64encode(bytes.fromhex(span[key])).decode()
    return Parse(json.dumps(payload),
                 trace_service_pb2.ExportTraceServiceRequest()).SerializeToString()


def export_phoenix(tracer, endpoint="http://127.0.0.1:6006/v1/traces"):
    """POST the tracer's spans to a Phoenix collector; returns the HTTP status."""
    response = httpx.post(endpoint, content=_to_protobuf(to_otlp(tracer.spans)),
                          headers={"Content-Type": "application/x-protobuf"})
    return response.status_code
