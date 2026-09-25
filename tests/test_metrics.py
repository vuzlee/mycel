"""The two ways the metrics can be wrong without anything going red.

One is a label whose values are unbounded, which is a memory leak in Prometheus that
nobody sees on the first day. The other is a trace that comes apart at the queue, which
produces two valid disconnected trees and no error at all.

Both are here rather than in a note because a note is not read by the person adding the
fifth metric.
"""

import asyncio

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import REGISTRY

from mycel.observability import metrics
from mycel.observability.metrics_server import serve_metrics
from mycel.queue import context

#: Anything whose value set grows with traffic. A series per job, per thread or per user is
#: a series that never dies, and Prometheus holds every one of them in memory for as long
#: as it runs.
FORBIDDEN_LABELS = frozenset(
    {"job_id", "thread_id", "conversation_id", "user_id", "issue_key", "request_id", "key"}
)


class TestNoLabelIsAnIdentifier:
    def test_every_mycel_metric_declares_only_bounded_labels(self) -> None:
        """Walks the real registry, so a metric added anywhere in `src/` is covered here
        without this file having to learn about it."""
        offenders = []
        for collector in list(REGISTRY._collector_to_names):
            for metric in collector.collect():
                if not metric.name.startswith("mycel_"):
                    continue
                for sample in metric.samples:
                    bad = FORBIDDEN_LABELS & set(sample.labels)
                    if bad:
                        offenders.append((metric.name, sorted(bad)))
        assert offenders == []

    def test_a_label_that_ends_in_id_is_the_shape_to_watch_for(self) -> None:
        """The named list above cannot anticipate the next identifier, so the suffix is
        checked too: `run_id`, `span_id`, `turn_id` all fail without an edit here."""
        metrics.jobs_total.labels(kind="chat", status="done").inc()
        for collector in list(REGISTRY._collector_to_names):
            for metric in collector.collect():
                if not metric.name.startswith("mycel_"):
                    continue
                for sample in metric.samples:
                    assert not [n for n in sample.labels if n.endswith("_id")], sample.labels


class TestTheFourMetricsExist:
    def test_render_names_all_four(self) -> None:
        """A metric is only in the output once it has been touched, so each is given one
        observation first — which is also the assertion that the labels it declares are
        the labels the call sites pass."""
        metrics.sync_duration_seconds.labels(domain="jira").observe(1.0)
        metrics.records_written.labels(domain="jira", layer="gold").set(3)
        metrics.tokens_spent_total.labels(model="cloud:x", direction="input").inc(10)
        metrics.jobs_total.labels(kind="chat", status="failed").inc()

        body, content_type = metrics.render()
        text = body.decode()
        assert "text/plain" in content_type
        for name in (
            "mycel_sync_duration_seconds",
            "mycel_records_written",
            "mycel_tokens_spent_total",
            "mycel_jobs_total",
        ):
            assert name in text


@pytest.mark.anyio
class TestTheScrapePort:
    """The worker and the scheduler have no HTTP layer, so this small server is the only
    thing standing between them and being invisible."""

    async def test_metrics_is_served_and_anything_else_is_404(self) -> None:
        server = await serve_metrics(0, "127.0.0.1")
        port = server.sockets[0].getsockname()[1]
        try:
            assert b"200 OK" in await _get(port, "/metrics")
            assert b"404" in await _get(port, "/")
        finally:
            server.close()
            await server.wait_closed()

    async def test_a_query_string_still_reaches_metrics(self) -> None:
        """Prometheus appends no query of its own, but a human checking by hand does."""
        server = await serve_metrics(0, "127.0.0.1")
        port = server.sockets[0].getsockname()[1]
        try:
            assert b"200 OK" in await _get(port, "/metrics?x=1")
        finally:
            server.close()
            await server.wait_closed()


async def _get(port: int, path: str) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nhost: localhost\r\n\r\n".encode())
    await writer.drain()
    body = await reader.read()
    writer.close()
    await writer.wait_closed()
    return body


class TestTheTraceSurvivesTheQueue:
    """`inject` and `extract` are two halves of one thing, and forgetting either reports
    nothing: spans keep being written, they just stop being one tree.

    Proved with a real span exporter rather than by comparing header strings, because the
    property that matters is parentage, which is what a header is only a means to.
    """

    def test_the_job_span_is_a_child_of_the_request_span(self) -> None:
        exporter, tracer = _recording_tracer()

        with tracer.start_as_current_span("request"):
            headers = context.inject()

        restored = context.extract(headers)
        assert restored is not None
        import opentelemetry.context as otel_context

        token = otel_context.attach(restored)
        try:
            with tracer.start_as_current_span("job"):
                pass
        finally:
            otel_context.detach(token)

        spans = {s.name: s for s in exporter.get_finished_spans()}
        request, job = spans["request"], spans["job"]
        assert job.parent is not None
        assert job.parent.span_id == request.context.span_id
        assert job.context.trace_id == request.context.trace_id

    def test_without_the_headers_the_job_starts_its_own_tree(self) -> None:
        """Not a failure: a job published by a CLI has no request to belong to. It is the
        state the test above must be able to tell itself apart from."""
        exporter, tracer = _recording_tracer()

        with tracer.start_as_current_span("request"):
            pass
        assert context.extract({}) is None

        with tracer.start_as_current_span("job"):
            pass

        spans = {s.name: s for s in exporter.get_finished_spans()}
        assert spans["job"].context.trace_id != spans["request"].context.trace_id


def _recording_tracer() -> tuple[InMemorySpanExporter, trace.Tracer]:
    """A provider of our own, not the global one: the global provider can only be set once
    per process and a test that set it would decide for every test after it."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter, provider.get_tracer("test")
