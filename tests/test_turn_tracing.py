"""A chat turn's trace, in the shape Langfuse reads: one root per turn, attributes on every span."""

from collections.abc import Iterator

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from mycel.observability import turns


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(turns.TurnAttributes())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(turns, "_tracer", provider.get_tracer("test"))
    yield exporter
    provider.shutdown()


def _turn(content: bool) -> None:
    with turns.chat_turn(
        question="When is the launch?",
        conversation_id=70,
        user_id=7,
        tags=["knowledge"],
        job_id="job-1",
        content=content,
    ) as trace:
        with turns.observe("retrieve-passages", "retriever", input="launch", content=content) as s:
            s.output(["The launch is Thursday."])
        trace.output("Thursday [c1].")


def test_the_turn_is_one_named_trace_with_readable_io(spans: InMemorySpanExporter) -> None:
    _turn(content=True)
    root = next(s for s in spans.get_finished_spans() if s.name == "answer-question")
    attrs = dict(root.attributes or {})

    assert attrs["langfuse.trace.name"] == "answer-question"
    assert attrs[turns.INPUT] == "When is the launch?"
    assert attrs[turns.OUTPUT] == "Thursday [c1]."
    assert attrs[f"{turns.METADATA}.job_id"] == "job-1"


def test_session_user_and_tags_reach_every_span(spans: InMemorySpanExporter) -> None:
    """Langfuse filters per observation: an attribute only on the root misses the children."""
    _turn(content=True)
    for span in spans.get_finished_spans():
        attrs = dict(span.attributes or {})
        assert attrs[turns.SESSION] == "70", span.name
        assert attrs[turns.USER] == "7", span.name
        assert attrs[turns.TAGS] == ("knowledge",), span.name


def test_the_lookup_is_a_retriever_under_the_turn(spans: InMemorySpanExporter) -> None:
    _turn(content=True)
    finished = {s.name: s for s in spans.get_finished_spans()}
    lookup, root = finished["retrieve-passages"], finished["answer-question"]

    assert dict(lookup.attributes or {})[turns.TYPE] == "retriever"
    assert lookup.parent is not None and lookup.parent.span_id == root.context.span_id


def test_the_turn_is_a_root_linked_to_the_request(spans: InMemorySpanExporter) -> None:
    """A parent from the api made Langfuse list the turn as a child, hidden under a root filter."""
    with turns._tracer.start_as_current_span("POST /chat") as request:
        _turn(content=True)
    root = next(s for s in spans.get_finished_spans() if s.name == "answer-question")

    assert root.parent is None
    assert root.context.trace_id != request.get_span_context().trace_id
    assert [link.context.span_id for link in root.links] == [request.get_span_context().span_id]


def test_no_content_leaves_without_consent(spans: InMemorySpanExporter) -> None:
    """OTEL_CAPTURE_CONTENT off: questions, passages and answers stay on the machine."""
    _turn(content=False)
    for span in spans.get_finished_spans():
        attrs = dict(span.attributes or {})
        assert turns.INPUT not in attrs and turns.OUTPUT not in attrs, span.name


def test_pydantic_ai_spans_get_their_langfuse_type(spans: InMemorySpanExporter) -> None:
    tracer = turns._tracer
    with tracer.start_as_current_span("invoke_agent analyst"):
        with tracer.start_as_current_span("execute_tool run_sql"):
            pass
    types = {s.name: dict(s.attributes or {}).get(turns.TYPE) for s in spans.get_finished_spans()}

    assert types == {"invoke_agent analyst": "agent", "execute_tool run_sql": "tool"}
