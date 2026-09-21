"""Put due dates on a calendar, so they can be glanced at on a phone.

One-way, and it will stay that way. A calendar event has a start and an end and nothing
else — no status, no parent, no estimate, no dependency — so encoding an epic into an
event title would be the hashtag trick wearing a different hat. Work is read from Jira and
nothing is ever read back out of here.

Idempotent by construction: the event id is derived from the issue key, so a re-sync
updates the event someone already has in their week instead of adding a second one. An
issue whose due date is removed has its event deleted, because a deadline that no longer
exists is worse on a calendar than one that never appeared.

A service account rather than note 015's per-user OAuth: this is the deployment writing to
its own calendar on a timer, with nobody signed in to consent. The account only sees the
calendar it has been shared into.
"""

import base64
from typing import Any

import httpx2
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.gold import WorkItemRow

API = "https://www.googleapis.com/calendar/v3"
SCOPES = ("https://www.googleapis.com/auth/calendar.events",)
HTTP_TIMEOUT_S = 15.0

log = get_logger(__name__)


async def publish_due_dates(items: list[WorkItemRow]) -> int:
    """Mirror every due date onto the calendar, and clear the ones that are gone.

    Returns how many events were written or removed. Zero for a deployment that has not
    configured a calendar, which is a normal state and not a failure.
    """
    settings = get_settings()
    calendar_id = settings.google_calendar_id
    if not calendar_id or not settings.google_service_account_json:
        log.debug("calendar not configured")
        return 0

    try:
        token = _token(settings.google_service_account_json)
    except (OSError, ValueError) as exc:
        log.warning("calendar credentials unusable", extra={"error": str(exc)})
        return 0

    touched = 0
    headers = {"authorization": f"Bearer {token}"}
    async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S, headers=headers) as client:
        for item in items:
            if await _apply(client, calendar_id, item):
                touched += 1

    log.info("calendar updated", extra={"events": touched, "calendar_id": calendar_id})
    return touched


async def _apply(client: httpx2.AsyncClient, calendar_id: str, item: WorkItemRow) -> bool:
    """One issue: its event written, or removed if it no longer has a due date."""
    url = f"{API}/calendars/{calendar_id}/events/{event_id(item.issue_key)}"
    try:
        if item.due_at is None:
            response = await client.delete(url)
            # 404 and 410 both mean "there is no such event", which is the desired state.
            return response.status_code in (200, 204, 404, 410)

        # PUT rather than POST: with the id chosen by us, an update and an insert are the
        # same call, and there is no window in which a second event can be created.
        response = await client.put(url, json=_event(item))
        response.raise_for_status()
    except httpx2.HTTPError as exc:
        log.warning("calendar write failed", extra={"issue_key": item.issue_key, "error": str(exc)})
        return False
    return True


def _event(item: WorkItemRow) -> dict[str, Any]:
    """One all-day event. The date, not the hour: Jira's due date has no time of day, and
    inventing 9am would put a false precision on a phone's lock screen."""
    assert item.due_at is not None
    day = item.due_at.date().isoformat()
    return {
        "summary": f"{item.issue_key} · {item.title}",
        "description": f"{item.kind} · {item.status} · {item.assignee_name or 'Unassigned'}",
        "start": {"date": day},
        # Google's end date is exclusive, so a one-day event ends the day it starts.
        "end": {"date": day},
        "transparency": "transparent",
    }


def event_id(issue_key: str) -> str:
    """A calendar id for one issue, the same one every time.

    Google allows lowercase base32hex and between 5 and 1024 characters, which `MYC-7` is
    not — so the key is encoded rather than cleaned up. Encoded and not hashed, because a
    reversible id makes an unexpected event traceable back to the issue that wrote it.

    The prefix is `mcl` and not `mycel` for the same reason: base32hex stops at `v`, so a
    `y` in the marker would make every id this writes illegal.
    """
    encoded = base64.b32hexencode(issue_key.encode()).decode().rstrip("=").lower()
    return f"mcl{encoded}"


def _token(key_file: str) -> str:
    """A fresh access token from the service-account key.

    Blocking, and deliberately not wrapped: it is one signed JWT exchanged once per sync,
    and moving it to a thread would cost more than it takes.
    """
    # `google-auth` ships no annotations for this constructor, so mypy sees an untyped
    # call in a typed module rather than anything actually unchecked.
    credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
        key_file, scopes=SCOPES
    )
    credentials.refresh(Request())
    return str(credentials.token)
