"""The calendar transport: reading one person's week, and writing one event to it.

Batch 051 turned this file inside out. It used to test a one-way sync that mirrored Jira due
dates onto a calendar the deployment owned, on a timer, with a service account — and nothing
ever called it. Eight tests about idempotent event ids went with it.

What is worth pinning now is narrower and sharper:

**`timeZone` on every `dateTime`.** Drop it and Google falls back to the calendar's default,
so a UTC host books every meeting seven hours off — silently, in the right format, at the
wrong time. That is the one bug here a person would only find by missing a meeting, so it is
asserted in both directions.

**`singleEvents`.** Without it a weekly standup comes back once, as the rule that makes it,
and "what have I got tomorrow" quietly omits it.

No request leaves the machine: `httpx2.MockTransport` answers for the API, and the token is
patched because `services/google_oauth.py` owns that half.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest

from mycel.core.config import get_settings
from mycel.notify import calendar
from mycel.services.google_oauth import GoogleError

pytestmark = pytest.mark.anyio

#: Captured before any test patches the name, so the factory below builds a real client
#: rather than recursing into its own replacement.
_REAL_CLIENT = httpx2.AsyncClient


def _mock(handler: Any) -> Any:
    def _client(**kwargs: Any) -> httpx2.AsyncClient:
        kwargs.pop("transport", None)
        return _REAL_CLIENT(transport=httpx2.MockTransport(handler), **kwargs)

    return _client


def _sent(sink: list[httpx2.Request], payload: dict[str, Any], status: int = 200) -> Any:
    """Record every request and answer it, so a test can read what went out."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        sink.append(request)
        return httpx2.Response(status, json=payload)

    return _mock(handler)


def _item(summary: str = "standup", hour: int = 9, all_day: bool = False) -> dict[str, Any]:
    """One of Google's event objects, in the shape the API actually returns."""
    if all_day:
        edge: dict[str, Any] = {"start": {"date": "2026-10-02"}, "end": {"date": "2026-10-03"}}
    else:
        edge = {
            "start": {"dateTime": f"2026-10-02T{hour:02d}:00:00+07:00"},
            "end": {"dateTime": f"2026-10-02T{hour:02d}:30:00+07:00"},
        }
    return {"summary": summary, "htmlLink": "https://calendar.google.com/event?eid=abc", **edge}


@pytest.fixture(autouse=True)
def bangkok(monkeypatch: pytest.MonkeyPatch) -> None:
    """A zone that is not UTC, because a UTC-only suite cannot catch a missing `timeZone`."""
    monkeypatch.setenv("TIMEZONE", "Asia/Bangkok")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def token(monkeypatch: pytest.MonkeyPatch) -> None:
    """The grant is `services/google_oauth.py`'s; here it is a string in a header."""

    async def _token(user_id: int) -> str:
        return "access-token"

    monkeypatch.setattr(calendar, "token_for", _token)


class TestReadingAWeek:
    async def test_the_window_asked_for_is_the_window_requested(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Someone asked about this afternoon, and `timeMax` is what makes it this afternoon."""
        sink: list[httpx2.Request] = []
        monkeypatch.setattr(httpx2, "AsyncClient", _sent(sink, {"items": []}))

        await calendar.list_events(1, hours=12)
        asked = datetime.fromisoformat(sink[0].url.params["timeMax"])
        assert timedelta(hours=11) < asked - datetime.now(UTC) <= timedelta(hours=12)

    async def test_a_repeating_event_is_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`singleEvents` is one parameter and the whole of whether a standup appears."""
        sink: list[httpx2.Request] = []
        monkeypatch.setattr(httpx2, "AsyncClient", _sent(sink, {"items": []}))

        await calendar.list_events(1, hours=24)
        assert sink[0].url.params["singleEvents"] == "true"
        assert sink[0].url.params["orderBy"] == "startTime"

    async def test_the_zone_is_sent_when_reading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sink: list[httpx2.Request] = []
        monkeypatch.setattr(httpx2, "AsyncClient", _sent(sink, {"items": []}))

        await calendar.list_events(1, hours=24)
        assert sink[0].url.params["timeZone"] == "Asia/Bangkok"

    async def test_an_event_is_read_in_the_teams_zone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nine in Bangkok must read as nine, not as two in the morning on a UTC host."""
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], {"items": [_item(hour=9)]}))

        events = await calendar.list_events(1, hours=24)
        assert events[0].starts_at.hour == 9
        assert events[0].summary == "standup"
        assert events[0].link.startswith("https://calendar.google.com/")

    async def test_an_all_day_entry_is_marked_as_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Google's `date` against its `dateTime` is how "Tuesday" differs from "Tuesday at
        three", and printing midnight for the first would invent a precision."""
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], {"items": [_item(all_day=True)]}))

        events = await calendar.list_events(1, hours=48)
        assert events[0].all_day is True
        assert events[0].starts_at.day == 2

    async def test_an_untitled_event_still_has_a_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A blank summary is legal in Google and would otherwise render an empty column."""
        item = _item()
        del item["summary"]
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], {"items": [item]}))

        assert (await calendar.list_events(1, hours=24))[0].summary == "(no title)"

    async def test_an_empty_calendar_is_an_empty_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], {}))

        assert await calendar.list_events(1, hours=24) == []


class TestWritingOne:
    async def test_the_zone_is_sent_with_both_edges(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The bug this whole module carries `timeZone` around to avoid: without it the event
        lands at the calendar's default offset, which on a UTC host is seven hours out."""
        sink: list[httpx2.Request] = []
        monkeypatch.setattr(httpx2, "AsyncClient", _sent(sink, _item(hour=15)))
        starts = datetime.fromisoformat("2026-10-02T15:00:00+07:00")

        await calendar.create_event(1, "review", starts, starts + timedelta(minutes=30))
        body = str(sink[0].read(), "utf-8")

        assert sink[0].method == "POST"
        assert body.count('"timeZone":"Asia/Bangkok"') == 2
        assert '"summary":"review"' in body

    async def test_the_event_comes_back_with_its_link(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The link is the whole of the follow-up: nothing here can edit or cancel."""
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], _item("review", hour=15)))
        starts = datetime.fromisoformat("2026-10-02T15:00:00+07:00")

        event = await calendar.create_event(1, "review", starts, starts + timedelta(minutes=30))
        assert event.link == "https://calendar.google.com/event?eid=abc"
        assert event.starts_at.hour == 15


class TestWhenGoogleWillNotAnswer:
    async def test_a_refusal_raises_rather_than_returning_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unlike the sync this replaced, there is a person waiting: "no events" would be a
        lie where "the calendar could not be reached" is the answer."""
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], {}, status=500))

        with pytest.raises(GoogleError):
            await calendar.list_events(1, hours=24)

    async def test_an_event_with_no_start_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], {"items": [{"summary": "odd"}]}))

        with pytest.raises(GoogleError):
            await calendar.list_events(1, hours=24)
