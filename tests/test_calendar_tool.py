"""The three calendar tools, and the draft store under two of them."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx2
import pytest
from pydantic_ai import ModelRetry

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ToolFailed
from mycel.agents.tools import calendar as calendar_tool
from mycel.agents.tools.calendar import CONNECT, MAX_HOURS, MAX_MINUTES, build_toolset
from mycel.infra.redis import drafts
from mycel.llm.budget import JobBudget
from mycel.services.auth import Principal
from mycel.services.google_oauth import NotConnected
from mycel.sources import google_calendar
from tests.fakes import FakeRedis

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("bangkok", "google_token")]

_REAL_CLIENT = httpx2.AsyncClient


class Calls:
    """Every request the calendar made, and a canned answer for each."""

    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self.requests: list[httpx2.Request] = []
        self.payload = payload
        self.status = status

    def client(self, **kwargs: Any) -> httpx2.AsyncClient:
        kwargs.pop("transport", None)
        return _REAL_CLIENT(transport=httpx2.MockTransport(self._handle), **kwargs)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(self.status, json=self.payload)


def _event(hour: int, summary: str = "review") -> dict[str, Any]:
    return {
        "summary": summary,
        "htmlLink": "https://calendar.google.com/event?eid=abc",
        "start": {"dateTime": f"2026-10-02T{hour:02d}:00:00+07:00"},
        "end": {"dateTime": f"2026-10-02T{hour:02d}:30:00+07:00"},
    }


def _soon() -> str:
    """A start that is tomorrow whenever the suite runs, since `_parse` refuses the past."""
    return (datetime.now(google_calendar.zone()) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")


@pytest.fixture(autouse=True)
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()

    async def _get_client() -> FakeRedis:
        return fake

    monkeypatch.setattr(drafts, "get_client", _get_client)
    return fake


#: Whoever the run is for, unless a test says otherwise.
ASKER = Principal(id=7, email="dev@example.com")


def _ctx(principal: Principal | None = ASKER) -> Any:
    class _Ctx:
        deps = MycelDeps(
            job_id="job-1",
            budget=JobBudget("job-1", Decimal("1.00")),
            settings=AgentSettings(model_spec="local:qwen3-4b"),
            principal=principal,
        )
        messages: list[Any] = []

    return _Ctx()


@pytest.fixture
def ctx() -> Any:
    return _ctx()


@pytest.fixture
def tools() -> dict[str, Any]:
    toolset = build_toolset()
    return {name: tool.function for name, tool in toolset.tools.items()}


class TestDraftingWritesNothing:
    """The reason the write is split in two, asserted the only way that means anything."""

    async def test_a_draft_never_reaches_google(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = Calls({})
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        out = await tools["draft_event"](ctx, summary="review", starts_at=_soon(), minutes=30)

        assert calls.requests == [], "drafting must not touch the calendar"
        assert "Not booked yet" in out

    async def test_the_draft_reads_the_time_back_in_words(
        self, tools: dict[str, Any], ctx: Any
    ) -> None:
        """A weekday name is what makes a wrong day catchable; two ISO dates look alike."""
        starts = datetime.now(google_calendar.zone()) + timedelta(days=1)
        out = await tools["draft_event"](
            ctx, summary="review", starts_at=starts.strftime("%Y-%m-%dT%H:%M"), minutes=45
        )

        assert starts.strftime("%A") in out
        assert "45 minutes" in out
        assert "confirm_event" in out

    async def test_the_draft_is_kept_with_an_expiry(
        self, tools: dict[str, Any], ctx: Any, redis: FakeRedis
    ) -> None:
        """An abandoned draft must disappear on its own — there is nothing to clean up."""
        await tools["draft_event"](ctx, summary="review", starts_at=_soon())

        assert list(redis.ttls.values()) == [drafts.DRAFT_TTL_SECONDS]


class TestWhatDraftingRefuses:
    async def test_a_time_in_the_past_is_sent_back_with_today_in_it(
        self, tools: dict[str, Any], ctx: Any
    ) -> None:
        """Almost always a year or a weekday read wrong."""
        with pytest.raises(ModelRetry) as caught:
            await tools["draft_event"](ctx, summary="review", starts_at="2020-01-01T09:00")

        assert "Asia/Bangkok" in str(caught.value)

    async def test_a_time_that_is_not_a_time_is_sent_back(
        self, tools: dict[str, Any], ctx: Any
    ) -> None:
        with pytest.raises(ModelRetry):
            await tools["draft_event"](ctx, summary="review", starts_at="next Friday")

    async def test_a_length_longer_than_a_day_is_sent_back(
        self, tools: dict[str, Any], ctx: Any
    ) -> None:
        """Longer than a working day is a holiday, not a meeting — usually "3" read as hours."""
        with pytest.raises(ModelRetry) as caught:
            await tools["draft_event"](ctx, summary="review", starts_at=_soon(), minutes=5000)

        assert str(MAX_MINUTES) in str(caught.value)


class TestConfirming:
    async def test_confirming_books_the_drafted_time(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = Calls(_event(15))
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)
        drafted = await tools["draft_event"](ctx, summary="review", starts_at=_soon())
        draft_id = drafted.rsplit("draft_id=", 1)[1].rstrip(".")

        out = await tools["confirm_event"](ctx, draft_id=draft_id)

        assert [request.method for request in calls.requests] == ["POST"]
        assert out.startswith("Booked:")
        assert "https://calendar.google.com/" in out

    async def test_a_second_yes_books_nothing(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ "Yes, do it" twice over is one meeting. The draft is spent as it is read."""
        calls = Calls(_event(15))
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)
        drafted = await tools["draft_event"](ctx, summary="review", starts_at=_soon())
        draft_id = drafted.rsplit("draft_id=", 1)[1].rstrip(".")

        await tools["confirm_event"](ctx, draft_id=draft_id)
        again = await tools["confirm_event"](ctx, draft_id=draft_id)

        assert len(calls.requests) == 1
        assert "Nothing was written" in again

    async def test_a_draft_id_from_a_prompt_cannot_book_on_another_calendar(
        self, tools: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The id travels through a model's context."""
        calls = Calls(_event(15))
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)
        mine = _ctx(ASKER)
        theirs = _ctx(Principal(id=8, email="other@example.com"))
        drafted = await tools["draft_event"](mine, summary="review", starts_at=_soon())
        draft_id = drafted.rsplit("draft_id=", 1)[1].rstrip(".")

        out = await tools["confirm_event"](theirs, draft_id=draft_id)

        assert calls.requests == []
        assert "Nothing was written" in out

    async def test_an_unknown_draft_is_a_sentence_not_a_retry(
        self, tools: dict[str, Any], ctx: Any
    ) -> None:
        """There is no argument the model could fix."""
        out = await tools["confirm_event"](ctx, draft_id="never-existed")

        assert "expired" in out


class TestReadingTheCalendar:
    async def test_the_counts_lead(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ "Two meetings" and "two of eleven" are different answers."""
        calls = Calls({"items": [_event(9, "standup"), _event(15)]})
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        out = await tools["read_events"](ctx, hours=24)

        assert out.startswith("2 events in the next 24 hours")
        assert "Asia/Bangkok" in out
        assert "standup" in out

    async def test_every_line_carries_the_events_link(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The link is the source, in exactly the sense `validate_output` already means."""
        calls = Calls({"items": [_event(9)]})
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        out = await tools["read_events"](ctx, hours=24)

        for line in out.splitlines():
            if "|" in line and "Columns:" not in line:
                assert "https://calendar.google.com/" in line

    async def test_an_empty_afternoon_says_so(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Silence reads as a failed call, and a model retries what did not fail."""
        calls = Calls({"items": []})
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        assert "(nothing on the calendar)" in await tools["read_events"](ctx, hours=12)

    async def test_asking_for_more_than_the_cap_says_so(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cost, not permission — so it answers with what it can and names the limit."""
        calls = Calls({"items": []})
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        out = await tools["read_events"](ctx, hours=10_000)

        assert str(MAX_HOURS) in out and "10000 hours was asked for" in out

    async def test_a_window_of_nothing_is_refused(self, tools: dict[str, Any], ctx: Any) -> None:
        with pytest.raises(ModelRetry):
            await tools["read_events"](ctx, hours=0)

    async def test_a_calendar_that_will_not_answer_fails_rather_than_re_prompting(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not the model's to fix. The run survives — `tools/delegate.py` makes it a gap."""
        calls = Calls({}, status=500)
        monkeypatch.setattr(httpx2, "AsyncClient", calls.client)

        with pytest.raises(ToolFailed):
            await tools["read_events"](ctx, hours=24)


class TestWithNoAccountConnected:
    """Not a failure. The person asked something, and part of it may still be answerable."""

    async def test_reading_answers_with_where_to_connect(self, tools: dict[str, Any]) -> None:
        assert await tools["read_events"](_ctx(None), hours=24) == CONNECT

    async def test_drafting_answers_with_where_to_connect(self, tools: dict[str, Any]) -> None:
        assert (
            await tools["draft_event"](_ctx(None), summary="review", starts_at=_soon()) == CONNECT
        )

    async def test_a_revoked_grant_reads_as_not_connected(
        self, tools: dict[str, Any], ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Revoking access at Google is a thing people do."""

        async def _refuse(user_id: int) -> str:
            raise NotConnected("gone")

        monkeypatch.setattr(calendar_tool, "token_for", _refuse)

        assert await tools["read_events"](ctx, hours=24) == CONNECT
