"""Langfuse shape for a chat turn: one trace per turn, its session, user and human-readable I/O.

Trace-wide attributes travel as OTel baggage, and `TurnAttributes` copies them onto every span,
so each observation can be filtered by session, user, tag and environment.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import baggage, context, trace
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

#: Attribute keys Langfuse reads; see langfuse.com/integrations/native/opentelemetry.
SESSION = "langfuse.session.id"
USER = "langfuse.user.id"
TAGS = "langfuse.trace.tags"
TYPE = "langfuse.observation.type"
INPUT = "langfuse.observation.input"
OUTPUT = "langfuse.observation.output"
METADATA = "langfuse.observation.metadata"

_tracer = trace.get_tracer("mycel")


class TurnAttributes(SpanProcessor):
    """Every span gets the turn's session, user and tags, and pydantic-ai spans their type."""

    def on_start(self, span: Span, parent_context: context.Context | None = None) -> None:
        for key, value in baggage.get_all(parent_context).items():
            if key == TAGS:
                span.set_attribute(TAGS, str(value).split(","))
            elif key.startswith("langfuse."):
                span.set_attribute(key, str(value))
        name = span.name or ""
        if name.startswith("invoke_agent "):
            span.set_attribute(TYPE, "agent")
        elif name.startswith("execute_tool "):
            span.set_attribute(TYPE, "tool")

    def on_end(self, span: ReadableSpan) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


class Observation:
    """One open span, with the content gate applied to what it records."""

    def __init__(self, span: trace.Span, content: bool) -> None:
        self._span = span
        self._content = content

    def output(self, value: Any) -> None:
        if self._content:
            self._span.set_attribute(OUTPUT, _text(value))

    def metadata(self, **values: Any) -> None:
        for key, value in values.items():
            self._span.set_attribute(f"{METADATA}.{key}", _text(value))


@contextmanager
def chat_turn(
    *,
    question: str,
    conversation_id: int,
    user_id: int,
    tags: list[str],
    job_id: str,
    content: bool,
) -> Iterator[Observation]:
    """The root of one chat turn's trace: `answer-question`, input the question."""
    ctx = context.get_current()
    for key, value in ((SESSION, str(conversation_id)), (USER, str(user_id))):
        ctx = baggage.set_baggage(key, value, ctx)
    if tags:
        ctx = baggage.set_baggage(TAGS, ",".join(sorted(tags)), ctx)
    token = context.attach(ctx)
    try:
        with _tracer.start_as_current_span("answer-question") as span:
            span.set_attribute("langfuse.trace.name", "answer-question")
            span.set_attribute(TYPE, "chain")
            if content:
                span.set_attribute(INPUT, question)
            observation = Observation(span, content)
            observation.metadata(job_id=job_id)
            yield observation
    finally:
        context.detach(token)


@contextmanager
def observe(name: str, kind: str, *, input: Any = None, content: bool) -> Iterator[Observation]:
    """A child step of the turn, e.g. `retrieve-passages` as a `retriever`."""
    with _tracer.start_as_current_span(name) as span:
        span.set_attribute(TYPE, kind)
        if content and input is not None:
            span.set_attribute(INPUT, _text(input))
        yield Observation(span, content)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, default=str)
