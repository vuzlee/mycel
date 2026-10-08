"""The HTTP API: app."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mycel.api.app import WEB_DIST, create_app
from mycel.api.dependencies import current_user
from mycel.core.config import Settings
from mycel.infra.postgres.repositories.conversations import TurnRow
from mycel.infra.redis.results import JobResult
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


class TestTheSinglePageApp:
    """A reload at a deep route must serve the page, not a 404."""

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
    """Which doors are locked, and which deliberately are not."""

    @pytest.fixture
    def stranger(self) -> Iterator[TestClient]:
        """The same app with nobody signed in. No override, no cookie."""
        app = create_app(Settings(otel_enabled=False))
        with TestClient(app, raise_server_exceptions=False) as running:
            yield running

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("post", "/chat", {"question": "anything"}),
            ("get", "/chat/job-abc", None),
            ("get", "/chat/job-abc/events", None),
            ("get", "/projects", None),
            ("get", "/conversations", None),
            ("delete", "/conversations/1", None),
            ("put", "/conversations/1/pin", {"pinned": True}),
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
        """A health check that needs a login is not a health check."""
        assert stranger.get(path).status_code != 401


class TestMetricsAreNotOnTheAppPort:
    def test_the_public_port_does_not_serve_metrics(self, client: TestClient) -> None:
        """No authentication on /metrics, so it lives on its own listener, never here."""
        assert client.get("/metrics").status_code == 404
