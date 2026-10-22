"""Read and write the asker's Google calendar on their own token; never deletes."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx2

from mycel.core.logging import get_logger
from mycel.infra.http import shared
from mycel.plugins.errors import SourceError
from mycel.plugins.google.http import GOOGLE_TIMEOUT_SECONDS

API = "https://www.googleapis.com/calendar/v3"
#: The person's own calendar.
CALENDAR = "primary"

#: Enough for a week ahead without flooding the context.
MAX_EVENTS = 100

log = get_logger(__name__)


@dataclass(frozen=True)
class Event:
    """One calendar entry; no attendees or description, so no names reach the model."""

    summary: str
    starts_at: datetime
    ends_at: datetime
    link: str
    #: An all-day entry: Google gives a `date` with no time.
    all_day: bool = False


async def list_events(token: str, hours: int, tz: ZoneInfo) -> list[Event]:
    """Events from now to `hours` ahead, repeating events expanded, read in `tz`."""
    now = datetime.now(UTC)
    params = {
        "timeMin": now.isoformat(),
        "timeMax": (now + timedelta(hours=hours)).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": str(MAX_EVENTS),
        "timeZone": tz.key,
    }
    payload = await _call(token, "GET", f"/calendars/{CALENDAR}/events", params=params)
    items = payload.get("items", [])
    return [_event(item, tz) for item in items if isinstance(item, dict)]


async def create_event(
    token: str, summary: str, starts_at: datetime, ends_at: datetime, tz: ZoneInfo
) -> Event:
    """Put one event on this person's calendar, in their zone, and return it with its link."""
    zone = tz.key
    body = {
        "summary": summary,
        "start": {"dateTime": starts_at.isoformat(), "timeZone": zone},
        "end": {"dateTime": ends_at.isoformat(), "timeZone": zone},
    }
    payload = await _call(token, "POST", f"/calendars/{CALENDAR}/events", json=body)
    return _event(payload, tz)


async def _call(
    token: str,
    method: str,
    path: str,
    params: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One authorized request; raises `SourceError`."""
    try:
        response = await shared().request(
            method,
            f"{API}{path}",
            params=params,
            json=json,
            headers={"authorization": f"Bearer {token}"},
            timeout=GOOGLE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx2.HTTPError as exc:
        raise SourceError(f"the calendar could not be reached: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourceError("the calendar answered with something unreadable")
    return payload


def _event(item: dict[str, Any], tz: ZoneInfo) -> Event:
    """One Google event object as an `Event`; a `date` means all-day."""
    start = item.get("start", {}) or {}
    end = item.get("end", {}) or {}
    all_day = "date" in start
    return Event(
        summary=str(item.get("summary") or "(no title)"),
        starts_at=_when(start, tz),
        ends_at=_when(end, tz),
        link=str(item.get("htmlLink") or ""),
        all_day=all_day,
    )


def _when(edge: dict[str, Any], tz: ZoneInfo) -> datetime:
    """Google's start or end, in the asker's zone.

    Read into the asker's zone rather than the host's: a server in UTC would otherwise print
    a three o'clock meeting as eight in the morning, which is exactly the class of mistake
    this module carries `timeZone` everywhere to avoid.
    """
    raw = edge.get("dateTime") or edge.get("date")
    if not isinstance(raw, str):
        raise SourceError("the calendar returned an event with no start")
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        # An all-day entry is a bare date: midnight in the asker's zone.
        return moment.replace(tzinfo=tz)
    return moment.astimezone(tz)
