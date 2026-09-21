"""The HTTP shell: assembly, the request id, and how errors come back.

No model is ever called here — `conftest.py` forbids it, and since batch 004 the model
would run in another process anyway. The queue and the result store are stubbed, because
what these tests are about is the shell: that a request is accepted without waiting, that
failures map to the right status, and that the request id survives the trip.

Whether the orchestrator is any good is `test_orchestrator.py`'s question; whether the job
survives a broker is `test_queue.py`'s.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mycel.agents.core.exceptions import AgentError, ModelTimeout, RunawayStopped
from mycel.api import dependencies
from mycel.api.app import WEB_DIST, create_app
from mycel.api.dependencies import current_user
from mycel.api.middleware import HEADER
from mycel.core.config import Settings
from mycel.core.exceptions import ConfigError
from mycel.domains.threads import Thread
from mycel.infra.postgres.repositories.app import ConversationRow, ReportRow
from mycel.infra.redis.results import JobResult
from mycel.llm.budget import BudgetExceeded
from mycel.services.auth import Principal

#: Who every request in this file is made by. Signing in for real would need a database,
#: which is `test_auth.py`'s subject — here the shell is under test, not the login.
SIGNED_IN = Principal(id=1, email="tester@example.com")


def _signed_in(app: FastAPI) -> None:
    """Satisfy `Depends(current_user)` without a session table.

    Overridden rather than stubbed with a cookie: a cookie would still be looked up in
    Postgres, and these tests deliberately run without one.
    """
    app.dependency_overrides[current_user] = lambda: SIGNED_IN


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """An app with tracing off, so tests neither export spans nor need credentials."""
    dependencies.reset_caches()
    app = create_app(Settings(otel_enabled=False))
    _signed_in(app)
    with TestClient(app, raise_server_exceptions=False) as running:
        yield running
    dependencies.reset_caches()


def _queues(monkeypatch: pytest.MonkeyPatch, result: str | Exception) -> None:
    """Make the report domain accept a job or fail, with no broker anywhere in sight."""

    async def fake_request(user_id: int, question: str) -> str:
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("mycel.api.routes.reports.request_report", fake_request)


def _summaries(monkeypatch: pytest.MonkeyPatch, job_id: str) -> list[tuple[str, int]]:
    """Capture what the summary route asked the domain for, and queue nothing."""
    asked: list[tuple[str, int]] = []

    async def fake_request(user_id: int, project: str, days: int) -> str:
        asked.append((project, days))
        return job_id

    monkeypatch.setattr("mycel.api.routes.reports.request_summary", fake_request)
    return asked


def _stored(
    monkeypatch: pytest.MonkeyPatch,
    result: JobResult | None,
    kept: ReportRow | None = None,
) -> None:
    """Make both halves of "written twice" answer, with neither Redis nor Postgres here.

    Both, because the route reads both: Redis while a run is in flight, and the kept row
    once the TTL has passed. Stubbing only the first leaves the second reaching for a real
    database, which is a connection error dressed up as a 500.
    """

    async def fake_fetch(job_id: str) -> JobResult | None:
        return result

    async def fake_find(job_id: str) -> ReportRow | None:
        return kept

    monkeypatch.setattr("mycel.api.routes.reports.results.fetch", fake_fetch)
    monkeypatch.setattr("mycel.api.routes.reports.find_report", fake_find)


#: What a finished run left behind, for the tests that read a kept row.
KEPT_BODY = {"findings": [], "gaps": ["nothing was asked"]}


def _kept(job_id: str, *, status: str = "done") -> ReportRow:
    """A row as `app.report` keeps it, for the fallback half of the result endpoint.

    A row that never ran has no body, which is how a `queued` one is told apart from a
    finished one without a second argument nobody reads.
    """
    return ReportRow(
        id=1,
        conversation_id=1,
        job_id=job_id,
        question="what happened?",
        status=status,
        body=KEPT_BODY if status == "done" else None,
        error=None,
        spent_usd=Decimal("0.0216"),
        created_at=datetime.now(UTC),
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
        """503, not a stack trace: a load balancer reads the code, and this endpoint is
        polled every few seconds while a dependency is down."""
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
        _queues(monkeypatch, "job-abc")
        response = client.post("/reports", json={"question": "what is true"})

        assert response.status_code == 202
        assert response.json() == {"job_id": "job-abc", "status": "accepted"}

    def test_an_empty_question_is_refused_before_anything_is_queued(
        self, client: TestClient
    ) -> None:
        assert client.post("/reports", json={"question": ""}).status_code == 422


class TestQueueingASummary:
    """The second kind of work, behind the same receipt and the same polling endpoint."""

    def test_a_summary_is_accepted_the_same_way_a_report_is(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _summaries(monkeypatch, "job-sum")
        response = client.post("/reports/summary", json={"project": "MYC", "days": 7})

        assert response.status_code == 202
        assert response.json() == {"job_id": "job-sum", "status": "accepted"}

    def test_the_window_defaults_rather_than_being_required(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A week, the same default the dashboard uses."""
        asked = _summaries(monkeypatch, "job-sum")
        client.post("/reports/summary", json={"project": "MYC"})

        assert asked == [("MYC", 7)]

    def test_a_year_is_an_export_not_a_standup(self, client: TestClient) -> None:
        assert (
            client.post("/reports/summary", json={"project": "MYC", "days": 365}).status_code == 422
        )


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
        """Only a miss in *both* stores is a 404: gone from Redis and never kept."""
        _stored(monkeypatch, None)
        assert client.get("/reports/nope").status_code == 404

    def test_a_dropped_key_falls_back_to_the_kept_row(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Past the TTL the report is still a report. This is why 012 kept it twice."""
        _stored(monkeypatch, None, kept=_kept("job-abc"))
        body = client.get("/reports/job-abc").json()

        assert body["status"] == "done"
        assert body["report"]["gaps"] == ["nothing was asked"]
        assert body["spent_usd"] == "0.0216"

    def test_a_kept_row_that_never_ran_is_not_running(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A job still `queued` when Redis forgot it is failed, not in flight.

        Telling a caller `running` sends them polling a job nobody will ever finish.
        """
        _stored(monkeypatch, None, kept=_kept("job-abc", status="queued"))
        assert client.get("/reports/job-abc").json()["status"] == "failed"


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
        _queues(monkeypatch, raised)
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
        _queues(monkeypatch, RuntimeError("this is a bug"))
        assert client.post("/reports", json={"question": "anything"}).status_code == 500

    def test_no_error_response_leaks_a_traceback(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _queues(monkeypatch, ConfigError("GEMINI_API_KEY is unset"))
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

        async def first_waits(user_id: int, question: str) -> str:
            if question == "slow":
                started.set()
                await asyncio.get_running_loop().run_in_executor(None, release.wait, 5)
            return f"job-{question}"

        monkeypatch.setattr("mycel.api.routes.reports.request_report", first_waits)

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

        async def one_span(user_id: int, question: str) -> str:
            with provider.get_tracer("test").start_as_current_span("publish"):
                return "job-abc"

        monkeypatch.setattr("mycel.api.routes.reports.request_report", one_span)

        dependencies.reset_caches()
        app = create_app(Settings(otel_enabled=False))
        _signed_in(app)
        with TestClient(app) as client:
            assert client.post("/reports", json={"question": "trace me"}).status_code == 202

        spans = {span.name: span for span in exporter.get_finished_spans()}
        publish_span = spans["publish"]
        assert publish_span.parent is not None, "the publish span has no parent — two trees"

        http_span = next(span for span in exporter.get_finished_spans() if span.name != "publish")
        assert publish_span.context.trace_id == http_span.context.trace_id

        trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]


class TestTheLists:
    """The two lists a page reads before it can ask for anything else."""

    def test_projects_are_filtered_by_permission(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The route lists what this person may read, not what the deployment has.

        Today `may_read_project` says yes to everyone, which is exactly why this test
        asserts against the filter rather than against its current answer.
        """

        async def fake_projects() -> list[str]:
            return ["MYC", "OPS"]

        async def fake_may_read(user: Principal, project: str) -> bool:
            return project == "MYC"

        monkeypatch.setattr("mycel.api.routes.projects.known_projects", fake_projects)
        monkeypatch.setattr("mycel.api.routes.projects.may_read_project", fake_may_read)

        assert client.get("/projects").json() == ["MYC"]

    def test_threads_are_this_person_s(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whose sidebar it is comes from the session, never from the query string."""
        asked: list[int] = []

        async def fake_threads(user_id: int, limit: int = 50) -> list[Thread]:
            asked.append(user_id)
            return [
                Thread(
                    conversation=ConversationRow(
                        id=7,
                        user_id=user_id,
                        title="what happened?",
                        kind="report",
                        created_at=datetime.now(UTC),
                    ),
                    job_id="job-abc",
                    status="done",
                )
            ]

        monkeypatch.setattr("mycel.api.routes.projects.list_threads", fake_threads)
        body = client.get("/conversations").json()

        assert asked == [SIGNED_IN.id]
        assert body[0]["job_id"] == "job-abc"

    def test_a_thread_nobody_ran_still_shows(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A queued run the worker never picked up is the row someone most needs to see."""

        async def fake_threads(user_id: int, limit: int = 50) -> list[Thread]:
            return [
                Thread(
                    conversation=ConversationRow(
                        id=8,
                        user_id=user_id,
                        title="never started",
                        kind="report",
                        created_at=datetime.now(UTC),
                    ),
                    job_id=None,
                    status=None,
                )
            ]

        monkeypatch.setattr("mycel.api.routes.projects.list_threads", fake_threads)
        body = client.get("/conversations").json()

        assert len(body) == 1 and body[0]["job_id"] is None


class TestTheSinglePageApp:
    """A reload at a deep route must serve the page, not a 404.

    Skipped rather than failed without a build: the UI is a client of this service, and a
    source checkout that has never run `npm run build` is a normal state.
    """

    @pytest.mark.skipif(not WEB_DIST.is_dir(), reason="web/dist not built")
    @pytest.mark.parametrize("path", ["/app/", "/app/home", "/app/login", "/app/register"])
    def test_every_route_serves_the_page(self, client: TestClient, path: str) -> None:
        response = client.get(path)

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @pytest.mark.skipif(not WEB_DIST.is_dir(), reason="web/dist not built")
    def test_a_missing_asset_is_still_missing(self, client: TestClient) -> None:
        """HTML in place of a missing `.js` hides a broken build behind a syntax error."""
        assert client.get("/app/assets/nope.js").status_code == 404


class TestWhatNeedsALogin:
    """Which doors are locked, and which deliberately are not.

    This is the test that catches a route added later without `Depends(current_user)` —
    the failure mode is silent, because an open endpoint works perfectly for everyone.
    """

    @pytest.fixture
    def stranger(self) -> Iterator[TestClient]:
        """The same app with nobody signed in. No override, no cookie."""
        dependencies.reset_caches()
        app = create_app(Settings(otel_enabled=False))
        with TestClient(app, raise_server_exceptions=False) as running:
            yield running
        dependencies.reset_caches()

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("post", "/reports", {"question": "anything"}),
            ("post", "/reports/summary", {"project": "MYC"}),
            ("get", "/reports/job-abc", None),
            ("get", "/reports/job-abc/events", None),
            ("get", "/projects", None),
            ("get", "/conversations", None),
        ],
    )
    def test_a_stranger_gets_401(
        self, stranger: TestClient, method: str, path: str, body: dict[str, Any] | None
    ) -> None:
        """A valid body on the POSTs, so a 422 cannot stand in for the 401 being tested."""
        response = getattr(stranger, method)(path, **({"json": body} if body else {}))
        assert response.status_code == 401

    @pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
    def test_health_does_not_need_one(self, stranger: TestClient, path: str) -> None:
        """A health check that needs a login is not a health check: a load balancer has
        no account, and a 401 reads as a healthy service to nothing at all."""
        assert stranger.get(path).status_code != 401
