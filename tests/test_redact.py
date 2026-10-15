"""A key a run holds never leaves in a log line or an exported span."""

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from mycel.core import redact
from mycel.observability.export import QuietExporter

KEY = "sk-or-v1-planted-0123456789abcdef"


def test_a_held_key_is_scrubbed_and_a_released_one_is_not_kept() -> None:
    with redact.holding(KEY):
        assert redact.scrub(f"Authorization: Bearer {KEY}") == "Authorization: Bearer [redacted]"
    assert redact.scrub(KEY) == KEY, "nothing is kept once the run ends"


def test_short_values_are_not_treated_as_secrets() -> None:
    with redact.holding("abc"):
        assert redact.scrub("abc def") == "abc def"


def test_overlapping_runs_keep_a_shared_key_until_both_end() -> None:
    with redact.holding(KEY):
        with redact.holding(KEY):
            pass
        assert redact.scrub(KEY) == redact.REDACTED


def test_an_exported_span_carries_no_held_key() -> None:
    inner = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(QuietExporter(inner)))
    tracer = provider.get_tracer("t")

    with redact.holding(KEY):
        with tracer.start_as_current_span("chat") as span:
            span.set_attribute("error", f"401 for key {KEY}")
            span.set_attribute("tags", ["a", KEY])

    exported = inner.get_finished_spans()[0].attributes or {}
    assert KEY not in str(dict(exported))
    assert redact.REDACTED in str(exported["error"])
