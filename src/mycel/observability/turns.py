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

from mycel.core.redact import scrub

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
    # A new trace per turn: the request that queued it is a link, not a parent, so the turn
    # is the root Langfuse lists and names, whatever the api exported.
    parent = trace.get_current_span(ctx).get_span_context()
    links = [trace.Link(parent)] if parent.is_valid else []
    ctx = trace.set_span_in_context(trace.INVALID_SPAN, ctx)
    token = context.attach(ctx)
    try:
        with _tracer.start_as_current_span("answer-question", links=links) as span:
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


#: Attributes that only repeat another one or serve Logfire's UI; they land in Langfuse's
#: metadata as noise.
NOISE_PREFIXES = ("logfire.",)
NOISE_KEYS = frozenset({"agent_name", "model_name"})


def _scrubbed(value: Any) -> Any:
    """Live secrets out of a string attribute, or of each string in a list of them."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, (list, tuple)):
        return type(value)(scrub(v) if isinstance(v, str) else v for v in value)
    return value


def without_noise(span: ReadableSpan) -> ReadableSpan:
    """The span with framework-only attributes and live secrets dropped, the rest as it was."""
    attrs = span.attributes or {}
    kept = {
        k: _scrubbed(v)
        for k, v in attrs.items()
        if k not in NOISE_KEYS and not k.startswith(NOISE_PREFIXES)
    }
    if kept == dict(attrs):
        return span
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=kept,
        events=span.events,
        links=span.links,
        kind=span.kind,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )
