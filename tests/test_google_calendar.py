"""The calendar transport: reading one person's week, and writing one event to it."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest

from mycel.sources import SourceError, google_calendar

TOKEN = "access-token"

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("bangkok")]

#: Captured before patching, so the factory builds a real client.
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


class TestReadingAWeek:
    async def test_the_window_asked_for_is_the_window_requested(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Someone asked about this afternoon, and `timeMax` is what makes it this afternoon."""
        sink: list[httpx2.Request] = []
        monkeypatch.setattr(httpx2, "AsyncClient", _sent(sink, {"items": []}))

        await google_calendar.list_events(TOKEN, hours=12)
        asked = datetime.fromisoformat(sink[0].url.params["timeMax"])
        assert timedelta(hours=11) < asked - datetime.now(UTC) <= timedelta(hours=12)

    async def test_a_repeating_event_is_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`singleEvents` is one parameter and the whole of whether a standup appears."""
        sink: list[httpx2.Request] = []
        monkeypatch.setattr(httpx2, "AsyncClient", _sent(sink, {"items": []}))

        await google_calendar.list_events(TOKEN, hours=24)
        assert sink[0].url.params["singleEvents"] == "true"
        assert sink[0].url.params["orderBy"] == "startTime"

    async def test_the_zone_is_sent_when_reading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sink: list[httpx2.Request] = []
        monkeypatch.setattr(httpx2, "AsyncClient", _sent(sink, {"items": []}))

        await google_calendar.list_events(TOKEN, hours=24)
        assert sink[0].url.params["timeZone"] == "Asia/Bangkok"

    async def test_an_event_is_read_in_the_teams_zone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nine in Bangkok must read as nine, not as two in the morning on a UTC host."""
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], {"items": [_item(hour=9)]}))

        events = await google_calendar.list_events(TOKEN, hours=24)
        assert events[0].starts_at.hour == 9
        assert events[0].summary == "standup"
        assert events[0].link.startswith("https://calendar.google.com/")

    async def test_an_all_day_entry_is_marked_as_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Google's `date` against its `dateTime` is how "Tuesday" differs from "Tuesday at three",
        and printing midnight for the first would invent a precision.
        """
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], {"items": [_item(all_day=True)]}))

        events = await google_calendar.list_events(TOKEN, hours=48)
        assert events[0].all_day is True
        assert events[0].starts_at.day == 2

    async def test_an_untitled_event_still_has_a_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A blank summary is legal in Google and would otherwise render an empty column."""
        item = _item()
        del item["summary"]
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], {"items": [item]}))

        assert (await google_calendar.list_events(TOKEN, hours=24))[0].summary == "(no title)"

    async def test_an_empty_calendar_is_an_empty_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], {}))

        assert await google_calendar.list_events(TOKEN, hours=24) == []


class TestWritingOne:
    async def test_the_zone_is_sent_with_both_edges(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The bug this whole module carries `timeZone` around to avoid."""
        sink: list[httpx2.Request] = []
        monkeypatch.setattr(httpx2, "AsyncClient", _sent(sink, _item(hour=15)))
        starts = datetime.fromisoformat("2026-10-02T15:00:00+07:00")

        await google_calendar.create_event(TOKEN, "review", starts, starts + timedelta(minutes=30))
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

        event = await google_calendar.create_event(
            TOKEN, "review", starts, starts + timedelta(minutes=30)
        )
        assert event.link == "https://calendar.google.com/event?eid=abc"
        assert event.starts_at.hour == 15


class TestWhenGoogleWillNotAnswer:
    async def test_a_refusal_raises_rather_than_returning_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unlike the sync this replaced, there is a person waiting."""
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], {}, status=500))

        with pytest.raises(SourceError):
            await google_calendar.list_events(TOKEN, hours=24)

    async def test_an_event_with_no_start_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx2, "AsyncClient", _sent([], {"items": [{"summary": "odd"}]}))

        with pytest.raises(SourceError):
            await google_calendar.list_events(TOKEN, hours=24)
