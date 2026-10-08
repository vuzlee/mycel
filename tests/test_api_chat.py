"""The HTTP API: chat."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mycel.agents.core.exceptions import AgentError, ModelTimeout, RunawayStopped
from mycel.api.app import create_app
from mycel.api.dependencies import current_user
from mycel.api.middleware import HEADER
from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError
from mycel.infra.postgres.repositories.conversations import TurnRow
from mycel.infra.redis.results import JobResult
from mycel.llm.budget import BudgetExceeded
from mycel.services.auth import Principal

#: Who every request in this file is made by.
SIGNED_IN = Principal(id=1, email="tester@example.com")


def _signed_in(app: FastAPI) -> None:
    """Satisfy `Depends(current_user)` without a session table."""
    app.dependency_overrides[current_user] = lambda: SIGNED_IN


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """An app with tracing off, so tests neither export spans nor need credentials."""
    app = create_app(Settings(otel_enabled=False))
    _signed_in(app)
    with TestClient(app, raise_server_exceptions=False) as running:
        yield running


def _queues(monkeypatch: pytest.MonkeyPatch, result: str | Exception) -> None:
    """Make the chat domain accept a job or fail, with no broker anywhere in sight."""

    async def fake_request(
        user_id: int, question: str, conversation_id: int | None = None, chips: Any = None
    ) -> tuple[str, int]:
        if isinstance(result, Exception):
            raise result
        return result, conversation_id or 1

    monkeypatch.setattr("mycel.api.routes.chat.request_chat", fake_request)


def _stored(
    monkeypatch: pytest.MonkeyPatch,
    result: JobResult | None,
    kept: TurnRow | None = None,
) -> None:
    """Make everything the route reads answer, with neither Redis nor Postgres here."""

    async def fake_fetch(job_id: str) -> JobResult | None:
        return result

    async def fake_find(job_id: str) -> TurnRow | None:
        return kept

    async def no_citations(job_id: str) -> dict[str, Any] | None:
        return None

    monkeypatch.setattr("mycel.api.routes.chat.results.fetch", fake_fetch)
    monkeypatch.setattr("mycel.api.routes.chat.find_turn", fake_find)
    monkeypatch.setattr("mycel.api.routes.chat.citations.fetch", no_citations)


#: What a finished run left behind, for the tests that read a kept row.
KEPT_ANSWER = "Nothing was asked, so nothing happened."


def _kept(job_id: str, *, status: str = "done", age_s: float = 0.0) -> TurnRow:
    """A row as `app.turn` keeps it, for the fallback half of the result endpoint."""
    return TurnRow(
        id=1,
        conversation_id=1,
        job_id=job_id,
        question="what happened?",
        status=status,
        answer=KEPT_ANSWER if status == "done" else None,
        error=None,
        spent_usd=Decimal("0.0216"),
        steps=None,
        created_at=datetime.now(UTC) - timedelta(seconds=age_s),
    )


class _FakeSession:
    async def execute(self, statement: object) -> None:
        return None


def _database(monkeypatch: pytest.MonkeyPatch, up: bool) -> None:
    """Stand in for Postgres, so the API tests need no server."""

    @asynccontextmanager
    async def fake_scope() -> AsyncIterator[_FakeSession]:
        if not up:
            raise OSError("connection refused")
        yield _FakeSession()

    monkeypatch.setattr("mycel.api.health.session_scope", fake_scope)


class TestHealth:
    def test_liveness_answers_without_touching_anything(self, client: TestClient) -> None:
        assert client.get("/health/live").status_code == 200

    def test_readiness_reaches_the_database(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Readiness that checks nothing always passes, which is the same as no check."""
        _database(monkeypatch, up=True)
        assert client.get("/health/ready").json() == {"status": "ok", "database": "ok"}

    def test_an_unreachable_database_answers_503(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """503, not a stack trace: a load balancer reads the code, and this endpoint is polled every
        few seconds while a dependency is down.
        """
        _database(monkeypatch, up=False)
        response = client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["database"] == "unreachable"

    def test_liveness_ignores_a_dead_database(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole reason the two are separate endpoints."""
        _database(monkeypatch, up=False)
        assert client.get("/health/live").status_code == 200


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
        _queues(monkeypatch, ModelTimeout("gone"))
        response = client.post("/chat", json={"question": "anything"})
        assert response.headers[HEADER]
        assert response.json()["request_id"] == response.headers[HEADER]


class TestQueueingAQuestion:
    """202 and a job id, in milliseconds."""

    def test_a_request_is_accepted_rather_than_answered(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The status code is the contract: accepted, and not done."""
        _queues(monkeypatch, "job-abc")
        response = client.post("/chat", json={"question": "what is true"})

        assert response.status_code == 202
        assert response.json() == {
            "job_id": "job-abc",
            "conversation_id": 1,
            "status": "accepted",
        }

    def test_an_empty_question_is_refused_before_anything_is_queued(
        self, client: TestClient
    ) -> None:
        assert client.post("/chat", json={"question": ""}).status_code == 422

    def test_a_follow_up_names_the_thread_it_joins(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The conversation the caller asked for comes back, not a fresh one."""
        seen: list[int | None] = []

        async def fake_request(
            user_id: int, question: str, conversation_id: int | None = None, chips: Any = None
        ) -> tuple[str, int]:
            seen.append(conversation_id)
            return "job-2", conversation_id or 99

        monkeypatch.setattr("mycel.api.routes.chat.request_chat", fake_request)
        response = client.post("/chat", json={"question": "and last week?", "conversation_id": 7})

        assert response.status_code == 202
        assert seen == [7]
        assert response.json()["conversation_id"] == 7

    def test_someone_elses_thread_is_a_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """404, not 403: which of the two it was is the one thing worth hiding."""
        from mycel.services.chat import ConversationNotFound

        _queues(monkeypatch, ConversationNotFound(7))
        response = client.post("/chat", json={"question": "and last week?", "conversation_id": 7})

        assert response.status_code == 404


class TestCollectingAnAnswer:
    def test_a_finished_answer_comes_back_with_what_it_cost(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stored(
            monkeypatch,
            JobResult(
                job_id="job-abc",
                status="done",
                answer=KEPT_ANSWER,
                spent_usd="0.0216",
            ),
        )
        body = client.get("/chat/job-abc").json()

        assert body["status"] == "done"
        assert body["answer"] == KEPT_ANSWER
        # A string, not a float: money is Decimal everywhere else and JSON floats undo that.
        assert isinstance(body["spent_usd"], str)
        Decimal(body["spent_usd"])

    def test_a_running_job_says_so_rather_than_404ing(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A poller must be able to tell "not yet" from "never"."""
        _stored(monkeypatch, JobResult(job_id="job-abc", status="running"))
        body = client.get("/chat/job-abc").json()

        assert body["status"] == "running"
        assert body["answer"] is None

    def test_a_failed_job_carries_its_reason(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stored(monkeypatch, JobResult(job_id="job-abc", status="failed", error="provider 503"))
        body = client.get("/chat/job-abc").json()

        assert body["status"] == "failed"
        assert "provider 503" in body["error"]

    def test_an_unknown_job_is_a_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only a miss in *both* stores is a 404: gone from Redis and never kept."""
        _stored(monkeypatch, None)
        assert client.get("/chat/nope").status_code == 404

    def test_a_dropped_key_falls_back_to_the_kept_row(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Past the TTL the answer is still the answer. This is why 012 kept it twice."""
        _stored(monkeypatch, None, kept=_kept("job-abc"))
        body = client.get("/chat/job-abc").json()

        assert body["status"] == "done"
        assert body["answer"] == KEPT_ANSWER
        assert body["spent_usd"] == "0.0216"

    def test_a_kept_row_that_never_ran_is_not_running(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A job still `queued` when Redis forgot it is failed, not in flight."""
        stale = get_settings().result_ttl_seconds + 60
        _stored(monkeypatch, None, kept=_kept("job-abc", status="queued", age_s=stale))
        assert client.get("/chat/job-abc").json()["status"] == "failed"

    def test_a_run_still_on_its_way_to_a_worker_is_running(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The window every run passes through, and the one the page polls in."""
        _stored(monkeypatch, None, kept=_kept("job-abc", status="queued", age_s=0.5))
        assert client.get("/chat/job-abc").json()["status"] == "running"

    def test_a_running_run_still_names_its_thread_and_its_question(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Redis says `running`; the thread and the question come off the kept row."""
        _stored(monkeypatch, JobResult(job_id="job-abc", status="running"), kept=_kept("job-abc"))
        body = client.get("/chat/job-abc").json()

        assert body["status"] == "running"
        assert body["conversation_id"] == 1
        assert body["question"] == "what happened?"

    def test_a_dropped_key_still_names_its_thread_and_its_question(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Past the TTL both still come from `app.turn`, same as the answer does."""
        _stored(monkeypatch, None, kept=_kept("job-abc"))
        body = client.get("/chat/job-abc").json()

        assert body["conversation_id"] == 1
        assert body["question"] == "what happened?"


class TestErrorsComeBackAsThemselves:
    """The mapping is the point: these are not all 500s."""

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
        _queues(monkeypatch, raised)
        response = client.post("/chat", json={"question": "anything"})
        assert response.status_code == status
        assert response.json()["error"] == kind

    def test_a_plain_bug_is_not_dressed_up_as_a_handled_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anything that is not a `MycelError` must reach the server's own handler."""
        _queues(monkeypatch, RuntimeError("this is a bug"))
        assert client.post("/chat", json={"question": "anything"}).status_code == 500

    def test_no_error_response_leaks_a_traceback(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _queues(monkeypatch, ConfigError("GEMINI_API_KEYS is unset"))
        body = client.post("/chat", json={"question": "anything"}).text
        assert "Traceback" not in body
        assert "mycel/api" not in body


class TestTheThingsThatFailSilently:
    """Two properties that no ordinary test touches, neither caught by an ordinary test."""

    def test_a_slow_publish_does_not_block_another_request(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If anything on the path is sync and blocking, the second request waits."""
        import asyncio
        import threading

        started = threading.Event()
        release = threading.Event()

        async def first_waits(
            user_id: int, question: str, conversation_id: int | None = None, chips: Any = None
        ) -> tuple[str, int]:
            if question == "slow":
                started.set()
                await asyncio.get_running_loop().run_in_executor(None, release.wait, 5)
            return f"job-{question}", 1

        monkeypatch.setattr("mycel.api.routes.chat.request_chat", first_waits)

        slow: list[int] = []
        thread = threading.Thread(
            target=lambda: slow.append(client.post("/chat", json={"question": "slow"}).status_code)
        )
        thread.start()
        assert started.wait(5), "the first request never reached the queue layer"

        # The first is still in flight. If the loop were blocked this would never return.
        assert client.post("/chat", json={"question": "fast"}).status_code == 202

        release.set()
        thread.join(5)
        assert slow == [202]

    def test_the_publish_span_sits_under_the_http_span(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One trace, not two."""
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        # `setup_tracing` refuses a second provider in one process.
        monkeypatch.setattr("mycel.api.app.setup_tracing", lambda cfg: provider)

        async def one_span(
            user_id: int, question: str, conversation_id: int | None = None, chips: Any = None
        ) -> tuple[str, int]:
            with provider.get_tracer("test").start_as_current_span("publish"):
                return "job-abc", 1

        monkeypatch.setattr("mycel.api.routes.chat.request_chat", one_span)

        app = create_app(Settings(otel_enabled=False))
        _signed_in(app)
        with TestClient(app) as client:
            assert client.post("/chat", json={"question": "trace me"}).status_code == 202

        spans = {span.name: span for span in exporter.get_finished_spans()}
        publish_span = spans["publish"]
        assert publish_span.parent is not None, "the publish span has no parent — two trees"

        http_span = next(span for span in exporter.get_finished_spans() if span.name != "publish")
        assert publish_span.context.trace_id == http_span.context.trace_id

        trace._TRACER_PROVIDER = None
