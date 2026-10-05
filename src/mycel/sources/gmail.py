"""The Gmail connector: one person's recent message headers, and nothing else.

**Whose inbox is a token, not a setting.** It used to log into one mailbox from `.env`, so
every user who asked about "my mail" read the maintainer's. It now takes the asker's own
Google access token (`services/google_oauth.py`), granted `gmail.readonly`, and reads
their inbox through the Gmail API. No token, no mail.

**Headers only, enforced in one parameter.** `format=metadata` with three `metadataHeaders`
is the whole of the discipline: Gmail returns no body for it, whatever the scope allows.

Unlike `jira.py` this writes nothing down. Headers go into a prompt and are gone.
"""

import email.utils
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2

from mycel.core.logging import get_logger
from mycel.sources import SourceError

log = get_logger(__name__)

API = "https://gmail.googleapis.com/gmail/v1/users/me"
TIMEOUT_S = 20.0

#: Read but never parsed for content. Anything else would be a body by another name.
HEADERS = ("From", "Subject", "Date")

#: A message's permalink, which is what makes a mention of it checkable. The researcher
#: rejects a claim without a source, and for mail this is the source.
PERMALINK = "https://mail.google.com/mail/u/0/#all/{id}"


@dataclass(frozen=True)
class Header:
    """One message, as much of it as ever leaves Google."""

    sender: str
    subject: str
    sent_at: datetime | None
    link: str


@dataclass(frozen=True)
class Mailbox:
    """What one read of the mailbox found.

    `total` is carried so an answer can say how many messages it looked past. Three
    interesting out of forty-seven is a different statement from three out of three.
    """

    headers: list[Header]
    total: int
    hours: int


async def read_recent(access_token: str, hours: int, limit: int) -> Mailbox:
    """Headers of this person's messages received in the last `hours`, newest first."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    query = f"after:{int(since.timestamp())}"
    try:
        async with httpx2.AsyncClient(
            timeout=TIMEOUT_S, headers={"authorization": f"Bearer {access_token}"}
        ) as client:
            listed = await _get(client, "/messages", {"q": query, "maxResults": "500"})
            ids = [str(m["id"]) for m in listed.get("messages", []) if m.get("id")]
            headers = [h for h in [await _header(client, i) for i in ids[:limit]] if h]
    except httpx2.HTTPError as exc:
        raise SourceError(f"gmail: the mailbox could not be reached: {exc}") from exc
    total = int(listed.get("resultSizeEstimate", len(ids)))
    return Mailbox(headers=headers, total=max(total, len(ids)), hours=hours)


async def _get(client: "httpx2.AsyncClient", path: str, params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}{path}", params=params)
    if response.status_code in (401, 403):
        raise SourceError(
            "gmail: this Google account has not allowed Mycel to read mail — "
            "connect Google again in Settings"
        )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


async def _header(client: "httpx2.AsyncClient", message_id: str) -> Header | None:
    params = [("format", "metadata"), *(("metadataHeaders", h) for h in HEADERS)]
    payload = await _get(client, f"/messages/{message_id}", params)
    fields = {
        str(h.get("name", "")).lower(): str(h.get("value", ""))
        for h in (payload.get("payload") or {}).get("headers", [])
    }
    return Header(
        sender=fields.get("from", "(unknown sender)"),
        subject=fields.get("subject") or "(no subject)",
        sent_at=_sent_at(fields.get("date")),
        link=PERMALINK.format(id=message_id),
    )


def _sent_at(raw: str | None) -> datetime | None:
    """The Date header as an aware datetime, or None when it cannot be read."""
    if not raw:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
