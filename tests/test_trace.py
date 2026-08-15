"""shoplab.trace: span nesting, the decorator, tree printing, and OTLP export."""

import time

from shoplab import trace
from shoplab.trace import Tracer, to_otlp


def sample_tracer():
    tracer = Tracer()
    with tracer.span("root", kind="agent"):
        with tracer.span("call", kind="llm", model="test-model"):
            time.sleep(0.002)
    return tracer


# --- nesting and timing ------------------------------------------------------

def test_nested_spans_parent_chain_and_durations():
    tracer = Tracer()
    with tracer.span("root", kind="agent") as root:
        with tracer.span("child", kind="llm") as child:
            time.sleep(0.002)
            with tracer.span("grandchild") as grandchild:
                time.sleep(0.002)
    assert root.parent_id is None
    assert child.parent_id == root.span_id
    assert grandchild.parent_id == child.span_id
    assert [s.name for s in tracer.spans] == ["root", "child", "grandchild"]
    assert all(s.end is not None and s.duration_ms > 0 for s in tracer.spans)


def test_sibling_spans_share_a_parent():
    tracer = Tracer()
    with tracer.span("root"):
        with tracer.span("first"):
            pass
        with tracer.span("second"):
            pass
    root, first, second = tracer.spans
    assert first.parent_id == root.span_id
    assert second.parent_id == root.span_id     # stack popped between siblings


def test_open_span_has_no_duration_yet():
    tracer = Tracer()
    with tracer.span("outer") as outer:
        assert outer.end is None and outer.duration_ms is None
    assert outer.duration_ms is not None


def test_clear_resets_spans_and_stack():
    tracer = sample_tracer()
    tracer.clear()
    assert tracer.spans == [] and tracer._stack == []


# --- the decorator -----------------------------------------------------------

def test_traced_decorator_records_a_span_per_call():
    tracer = Tracer()

    @tracer.traced()
    def add(a, b):
        return a + b

    assert add(2, 3) == 5
    assert add(4, 5) == 9
    assert [s.name for s in tracer.spans] == ["add", "add"]
    assert all(s.end is not None for s in tracer.spans)


def test_traced_decorator_custom_name_and_kind():
    tracer = Tracer()

    @tracer.traced(name="lookup", kind="tool")
    def anything():
        return "x"

    anything()
    assert tracer.spans[0].name == "lookup"
    assert tracer.spans[0].kind == "tool"


# --- print_tree --------------------------------------------------------------

def test_print_tree_indents_children(capsys):
    tracer = sample_tracer()
    tracer.print_tree()
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("root")
    assert lines[1].startswith("  call")        # child indented under parent
    assert "llm" in lines[1] and "test-model" in lines[1]


# --- OTLP export -------------------------------------------------------------

def test_to_otlp_shape_hex_ids_and_ns_times():
    tracer = sample_tracer()
    payload = to_otlp(tracer.spans, project="proj-x")
    assert isinstance(payload["resourceSpans"], list)
    resource_spans = payload["resourceSpans"][0]
    assert isinstance(resource_spans["scopeSpans"], list)
    spans = resource_spans["scopeSpans"][0]["spans"]
    assert isinstance(spans, list) and len(spans) == 2
    for s in spans:
        assert len(s["traceId"]) == 32 and int(s["traceId"], 16) >= 0
        assert len(s["spanId"]) == 16 and int(s["spanId"], 16) >= 0
        start, end = int(s["startTimeUnixNano"]), int(s["endTimeUnixNano"])
        assert start > 10 ** 18 and end >= start        # unix-epoch nanoseconds
    root, call = spans
    assert call["parentSpanId"] == root["spanId"]
    assert root["parentSpanId"] == ""


def test_to_otlp_carries_the_project_attribute():
    payload = to_otlp(sample_tracer().spans, project="proj-x")
    attrs = payload["resourceSpans"][0]["resource"]["attributes"]
    assert {"key": "openinference.project.name",
            "value": {"stringValue": "proj-x"}} in attrs


def test_export_phoenix_posts_otlp_protobuf_without_network(monkeypatch):
    from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

    tracer = sample_tracer()
    calls = {}

    class FakeResponse:
        status_code = 200

    def fake_post(url, content=None, headers=None, **kwargs):
        calls["url"], calls["content"], calls["headers"] = url, content, headers
        return FakeResponse()

    monkeypatch.setattr(trace.httpx, "post", fake_post)
    status = trace.export_phoenix(tracer, endpoint="http://127.0.0.1:9999/v1/traces")
    assert status == 200
    assert calls["url"] == "http://127.0.0.1:9999/v1/traces"
    assert calls["headers"]["Content-Type"] == "application/x-protobuf"
    request = trace_service_pb2.ExportTraceServiceRequest.FromString(calls["content"])
    posted = request.resource_spans[0].scope_spans[0].spans
    assert len(posted) == len(tracer.spans)
    assert posted[1].parent_span_id == posted[0].span_id    # hex ids -> same raw bytes
    assert len(posted[0].trace_id) == 16                    # 32 hex chars -> 16 bytes
