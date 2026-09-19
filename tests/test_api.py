"""The HTTP shell: assembly, the request id, and how errors come back.

No model is ever called here — `conftest.py` forbids it, and since batch 004 the model
would run in another process anyway. The queue and the result store are stubbed, because
what these tests are about is the shell: that a request is accepted without waiting, that
failures map to the right status, and that the request id survives the trip.

Whether the orchestrator is any good is `test_orchestrator.py`'s question; whether the job
survives a broker is `test_queue.py`'s.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from mycel.agents.core.exceptions import AgentError, ModelTimeout, RunawayStopped
from mycel.api import dependencies
from mycel.api.app import create_app
from mycel.api.middleware import HEADER
from mycel.core.config import Settings
from mycel.core.exceptions import ConfigError
from mycel.llm.budget import BudgetExceeded
from mycel.storage.redis.results import JobResult


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """An app with tracing off, so tests neither export spans nor need credentials."""
    dependencies.reset_caches()
    app = create_app(Settings(otel_enabled=False))
    with TestClient(app, raise_server_exceptions=False) as running:
        yield running
    dependencies.reset_caches()


def _enqueues(monkeypatch: pytest.MonkeyPatch, result: str | Exception) -> None:
    """Make the queue accept a job or fail, with no broker anywhere in sight."""

    async def fake_enqueue(question: str) -> str:
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("mycel.api.routes.reports.enqueue_report", fake_enqueue)


def _stored(monkeypatch: pytest.MonkeyPatch, result: JobResult | None) -> None:
    """Make the result store answer, with no Redis anywhere in sight."""

    async def fake_fetch(job_id: str) -> JobResult | None:
        return result

    monkeypatch.setattr("mycel.api.routes.reports.results.fetch", fake_fetch)


class TestHealth:
    def test_liveness_answers_without_touching_anything(self, client: TestClient) -> None:
        assert client.get("/health/live").status_code == 200

    def test_readiness_is_a_separate_endpoint(self, client: TestClient) -> None:
        """Separate from liveness so a blinking dependency does not restart the container."""
        assert client.get("/health/ready").status_code == 200


class TestRequestId:
    def test_every_response_carries_one(self, client: TestClient) -> None:
        assert client.get("/health/live").headers[HEADER]

    def test_an_upstream_id_is_kept(self, client: TestClient) -> None:
        """Generating a fresh one would break the chain exactly where a reader needs it."""
        response = client.get("/health/live", headers={HEADER: "from-the-proxy"})
        assert response.headers[HEADER] == "from-the-proxy"

    def test_two_requests_get_different_ids(self, client: TestClient) -> None:
        """A contextvar that outlives its request would give the second one the first's."""
        first = client.get("/health/live").headers[HEADER]
        second = client.get("/health/live").headers[HEADER]
        assert first != second

    def test_an_id_survives_a_failing_request(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reset is in a `finally`, and this is what would catch it being moved."""
        _enqueues(monkeypatch, ModelTimeout("gone"))
        response = client.post("/reports", json={"question": "anything"})
        assert response.headers[HEADER]
        assert response.json()["request_id"] == response.headers[HEADER]


class TestQueueingAReport:
    """202 and a job id, in milliseconds. The batch 003 endpoint ran the report inline."""

    def test_a_request_is_accepted_rather_than_answered(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The status code is the contract: accepted, and not done.

        A caller that reads 202 as "here is your report" fails on the missing body rather
        than quietly treating a receipt as an answer.
        """
        _enqueues(monkeypatch, "job-abc")
        response = client.post("/reports", json={"question": "what is true"})

        assert response.status_code == 202
        assert response.json() == {"job_id": "job-abc", "status": "accepted"}

    def test_an_empty_question_is_refused_before_anything_is_queued(
        self, client: TestClient
    ) -> None:
        assert client.post("/reports", json={"question": ""}).status_code == 422


class TestCollectingAReport:
    def test_a_finished_report_comes_back_with_what_it_cost(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stored(
            monkeypatch,
            JobResult(
                job_id="job-abc",
                status="done",
                report={"findings": [], "gaps": ["nothing was asked"]},
                spent_usd="0.0216",
            ),
        )
        body = client.get("/reports/job-abc").json()

        assert body["status"] == "done"
        assert body["report"]["gaps"] == ["nothing was asked"]
        # A string, not a float: money is Decimal everywhere else and JSON floats undo that.
        assert isinstance(body["spent_usd"], str)
        Decimal(body["spent_usd"])

    def test_a_running_job_says_so_rather_than_404ing(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A poller must be able to tell "not yet" from "never"."""
        _stored(monkeypatch, JobResult(job_id="job-abc", status="running"))
        body = client.get("/reports/job-abc").json()

        assert body["status"] == "running"
        assert body["report"] is None

    def test_a_failed_job_carries_its_reason(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stored(monkeypatch, JobResult(job_id="job-abc", status="failed", error="provider 503"))
        body = client.get("/reports/job-abc").json()

        assert body["status"] == "failed"
        assert "provider 503" in body["error"]

    def test_an_unknown_job_is_a_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Expired and never-existed are the same answer, on purpose.

        See `storage/redis/results.py` for why.
        """
        _stored(monkeypatch, None)
        assert client.get("/reports/nope").status_code == 404


class TestErrorsComeBackAsThemselves:
    """The mapping is the point: these are not all 500s.

    A caller who asked for too much must not be told the server is broken, because the two
    call for opposite responses — one is retried, the other is reported.
    """

    @pytest.mark.parametrize(
        ("raised", "status", "kind"),
        [
            (BudgetExceeded("job", Decimal("1"), Decimal("2")), 402, "budget_exceeded"),
            (RunawayStopped("hit the ceiling"), 504, "runaway_stopped"),
            (ConfigError("no key"), 500, "config_error"),
            (AgentError("provider is down"), 502, "agent_failed"),
        ],
    )
    def test_each_failure_maps_to_its_own_status(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        raised: Exception,
        status: int,
        kind: str,
    ) -> None:
        _enqueues(monkeypatch, raised)
        response = client.post("/reports", json={"question": "anything"})
        assert response.status_code == status
        assert response.json()["error"] == kind

    def test_a_plain_bug_is_not_dressed_up_as_a_handled_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anything that is not a `MycelError` must reach the server's own handler.

        Catching it here would turn every bug into a tidy JSON body and lose the traceback,
        which is the one thing a bug needs to leave behind.
        """
        _enqueues(monkeypatch, RuntimeError("this is a bug"))
        assert client.post("/reports", json={"question": "anything"}).status_code == 500

    def test_no_error_response_leaks_a_traceback(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enqueues(monkeypatch, ConfigError("GEMINI_API_KEY is unset"))
        body = client.post("/reports", json={"question": "anything"}).text
        assert "Traceback" not in body
        assert "mycel/api" not in body


class TestTheThingsThatFailSilently:
    """Two properties that no ordinary test touches, both warned about in batch 003.

    Neither shows up as a wrong answer. The first shows up as a server that handles one
    request at a time under load; the second as two disconnected trees in Langfuse.

    The trace one matters more since batch 004, not less: the span the worker restores
    from the message headers attaches to the span this test is checking exists.
    """

    def test_a_slow_publish_does_not_block_another_request(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If anything on the path is sync and blocking, the second request waits.

        The report itself no longer runs here, but a publish still crosses the network and
        a blocking AMQP client on this path would serialise every caller. Asserted by
        having the first publish refuse to finish until the second has started, which can
        only happen if both are in flight at once. A blocking implementation deadlocks
        here instead of returning a wrong value.
        """
        import asyncio
        import threading

        started = threading.Event()
        release = threading.Event()

        async def first_waits(question: str) -> str:
            if question == "slow":
                started.set()
                await asyncio.get_running_loop().run_in_executor(None, release.wait, 5)
            return f"job-{question}"

        monkeypatch.setattr("mycel.api.routes.reports.enqueue_report", first_waits)

        slow: list[int] = []
        thread = threading.Thread(
            target=lambda: slow.append(
                client.post("/reports", json={"question": "slow"}).status_code
            )
        )
        thread.start()
        assert started.wait(5), "the first request never reached the queue layer"

        # The first is still in flight. If the loop were blocked this would never return.
        assert client.post("/reports", json={"question": "fast"}).status_code == 202

        release.set()
        thread.join(5)
        assert slow == [202]

    def test_the_publish_span_sits_under_the_http_span(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One trace, not two.

        This is the risk named in the batch note: HTTP spans and agent spans landing in
        separate trees makes the work done in `73b8b17` worthless, and nothing else in the
        suite would notice. Checked by recording spans in memory rather than exporting.
        """
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        # `setup_tracing` refuses to install a second provider in one process, so the app
        # is handed this one directly — the wiring under test is `instrument_app`, not
        # how the provider was built.
        monkeypatch.setattr("mycel.api.app.setup_tracing", lambda cfg: provider)

        async def one_span(question: str) -> str:
            with provider.get_tracer("test").start_as_current_span("publish"):
                return "job-abc"

        monkeypatch.setattr("mycel.api.routes.reports.enqueue_report", one_span)

        dependencies.reset_caches()
        with TestClient(create_app(Settings(otel_enabled=False))) as client:
            assert client.post("/reports", json={"question": "trace me"}).status_code == 202

        spans = {span.name: span for span in exporter.get_finished_spans()}
        publish_span = spans["publish"]
        assert publish_span.parent is not None, "the publish span has no parent — two trees"

        http_span = next(span for span in exporter.get_finished_spans() if span.name != "publish")
        assert publish_span.context.trace_id == http_span.context.trace_id

        trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
