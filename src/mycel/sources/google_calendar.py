"""Read and write one person's Google calendar, on a token they consented to.

Two calls, and both run as the person asking: `list_events` for "what have I got this
afternoon", `create_event` for "book that". Authorisation is `services/google_oauth.py`'s
and nothing here ever sees a refresh token.

**No sync, no service account.** A question has the asker right there, so every call runs
on their token. "What is due this week" is asked of `summariser`, which reads Jira and
needs no event to answer it.

**`timeZone` is sent with every `dateTime`, in both directions.** Without it Google falls
back to the calendar's own default, so a deployment on a UTC host books every meeting seven
hours off — silently, in the right format, at the wrong time. The zone is the team's, out of
`Settings`, the same one Jira due dates are read in.

**Nothing here deletes.** The scope asked for is `calendar.events`, an event carries a link,
and changing or cancelling one is done in Google where the person can see what they are
changing. A model that can delete an event is a model that can clear an afternoon.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx2

from mycel.core.config import get_settings, team_zone
from mycel.core.logging import get_logger
from mycel.services.google_oauth import GoogleError, token_for

API = "https://www.googleapis.com/calendar/v3"
#: The person's own calendar, always. Reading any other one needs a calendar id nobody has
#: typed in, and writing to one would be writing to somebody else's week.
CALENDAR = "primary"
HTTP_TIMEOUT_S = 15.0

#: Enough to answer "what does this week look like" and stop well short of a year, which
#: crosses the context window as cost rather than information.
MAX_EVENTS = 100

log = get_logger(__name__)


@dataclass(frozen=True)
class Event:
    """One entry on a calendar, as much of it as ever leaves Google.

    No attendees and no description on purpose: an attendee list is real people's names
    going into a model provider's prompt, which is the same line `sources/gmail.py` draws by
    reading headers and never bodies.
    """

    summary: str
    starts_at: datetime
    ends_at: datetime
    link: str
    #: True for a day the person blocked out rather than an hour they booked. Google models
    #: it as a `date` with no time, and printing midnight for it would invent a precision.
    all_day: bool = False


async def list_events(user_id: int, hours: int) -> list[Event]:
    """Everything on this person's calendar from now to `hours` ahead.

    `singleEvents` expands a repeating event into the occurrences that actually fall in the
    window: without it a weekly standup comes back once, as the rule that makes it, and the
    answer to "what have I got tomorrow" silently omits it.
    """
    now = datetime.now(UTC)
    params = {
        "timeMin": now.isoformat(),
        "timeMax": (now + timedelta(hours=hours)).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": str(MAX_EVENTS),
        "timeZone": get_settings().timezone,
    }
    payload = await _call(user_id, "GET", f"/calendars/{CALENDAR}/events", params=params)
    items = payload.get("items", [])
    return [_event(item) for item in items if isinstance(item, dict)]


async def create_event(user_id: int, summary: str, starts_at: datetime, ends_at: datetime) -> Event:
    """Put one event on this person's calendar and return it, with its link.

    The link is the whole of the follow-up: this is the only write in the file, so moving or
    cancelling what it made happens in Google, where the person can see the week they are
    changing.
    """
    zone = zone_name()
    body = {
        "summary": summary,
        "start": {"dateTime": starts_at.isoformat(), "timeZone": zone},
        "end": {"dateTime": ends_at.isoformat(), "timeZone": zone},
    }
    payload = await _call(user_id, "POST", f"/calendars/{CALENDAR}/events", json=body)
    return _event(payload)


def zone() -> ZoneInfo:
    return team_zone()


def zone_name() -> str:
    """The team's zone as an IANA name, which is what Google wants in `timeZone`."""
    return get_settings().timezone


async def _call(
    user_id: int,
    method: str,
    path: str,
    params: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One authorised request. Raises `GoogleError`, or `NotConnected` from `token_for`.

    Raising rather than logging and returning nothing, unlike the sync this replaced: there
    is a person waiting for an answer, and "no events" would be a lie where "your Google
    account is not connected" is the answer.
    """
    token = await token_for(user_id)
    try:
        async with httpx2.AsyncClient(
            timeout=HTTP_TIMEOUT_S, headers={"authorization": f"Bearer {token}"}
        ) as client:
            response = await client.request(method, f"{API}{path}", params=params, json=json)
            response.raise_for_status()
            payload = response.json()
    except httpx2.HTTPError as exc:
        raise GoogleError(f"the calendar could not be reached: {exc}") from exc
    if not isinstance(payload, dict):
        raise GoogleError("the calendar answered with something unreadable")
    return payload


def _event(item: dict[str, Any]) -> Event:
    """One of Google's event objects, as this module's own.

    A `date` where a `dateTime` was expected is an all-day entry, not a malformed one — the
    two shapes are how Google distinguishes "Tuesday" from "Tuesday at three".
    """
    start = item.get("start", {}) or {}
    end = item.get("end", {}) or {}
    all_day = "date" in start
    return Event(
        summary=str(item.get("summary") or "(no title)"),
        starts_at=_when(start),
        ends_at=_when(end),
        link=str(item.get("htmlLink") or ""),
        all_day=all_day,
    )


def _when(edge: dict[str, Any]) -> datetime:
    """Google's start or end, in the team's zone.

    Read into the team's zone rather than the host's: a server in UTC would otherwise print
    a three o'clock meeting as eight in the morning, which is exactly the class of mistake
    this module carries `timeZone` everywhere to avoid.
    """
    raw = edge.get("dateTime") or edge.get("date")
    if not isinstance(raw, str):
        raise GoogleError("the calendar returned an event with no start")
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        # An all-day entry is a bare date. Midnight in the team's zone is the only reading
        # that puts it on the day the person sees it.
        return moment.replace(tzinfo=zone())
    return moment.astimezone(zone())
