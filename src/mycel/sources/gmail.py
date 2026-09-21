"""The Gmail connector: recent message headers, and nothing else.

Unlike `jira.py` this one writes nothing down. Bronze exists so a parser that is wrong
today can be re-run against the original tomorrow, and there is no parser here — headers
go into a prompt and are gone. A tool call is one reading, not one loading.

**Headers only, enforced in one string.** `BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)]`
is the whole of the discipline. An app password is a real password with full mailbox
access and no narrower scope to ask for, so nothing outside this module can stop a body
being read — which makes that fetch string a line not to change without deciding to.

`PEEK` is the other half of the same string. Without it Gmail marks every message seen,
and as a tool that happens whenever somebody asks rather than once a morning.

`imaplib` is synchronous and from the stdlib. The caller wraps it in `asyncio.to_thread`,
because blocking here blocks the whole process.
"""

import email.utils
import imaplib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.sources import SourceError

log = get_logger(__name__)

HOST = "imap.gmail.com"
TIMEOUT_S = 20.0

#: Read but never parsed for content. Anything else would be a body by another name.
FETCH = "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"

#: A message's permalink, which is what makes a mention of it checkable. The researcher
#: rejects a claim without a source, and for mail this is the source.
PERMALINK = "https://mail.google.com/mail/u/0/#all/{uid}"


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


def read_recent(hours: int, limit: int) -> Mailbox:
    """Headers of messages received in the last `hours`. Blocking; call in a thread."""
    settings = get_settings()
    if settings.gmail_address is None or settings.gmail_app_password is None:
        raise SourceError("GMAIL_ADDRESS and GMAIL_APP_PASSWORD are not set")

    since = datetime.now(UTC) - timedelta(hours=hours)
    try:
        with _connect(settings.gmail_address, settings.gmail_app_password.get_secret_value()) as m:
            # IMAP's SINCE has a date's resolution, not an hour's, so it over-selects by
            # up to a day and `_recent` trims the rest against the real timestamp.
            status, data = m.uid("SEARCH", "SINCE", since.strftime("%d-%b-%Y"))
            if status != "OK":
                raise SourceError(f"the mailbox refused a search: {status}")
            uids = (data[0] or b"").split()
            # Newest first, so a cap drops the oldest rather than the most relevant.
            recent = list(reversed(uids))[:limit]
            headers = [h for uid in recent if (h := _fetch(m, uid)) is not None]
    except imaplib.IMAP4.error as exc:
        # Gmail's own message is the useful one: "invalid credentials" and "IMAP is
        # disabled for this account" are different problems with different fixes, and
        # IMAP being off is the trap — the login succeeds and the select fails.
        raise SourceError(f"the mailbox could not be read: {exc}") from exc
    except OSError as exc:
        raise SourceError(f"could not reach {HOST}: {exc}") from exc

    kept = [h for h in headers if h.sent_at is None or h.sent_at >= since]
    log.info(
        "read gmail headers",
        extra={"hours": hours, "matched": len(uids), "returned": len(kept)},
    )
    return Mailbox(headers=kept, total=len(uids), hours=hours)


def _connect(address: str, password: str) -> imaplib.IMAP4_SSL:
    """A logged-in connection with the inbox selected read-only.

    `readonly=True` is belt to `PEEK`'s braces: two independent reasons the mailbox is
    not modified, either of which would do on its own.
    """
    mailbox = imaplib.IMAP4_SSL(HOST, timeout=TIMEOUT_S)
    mailbox.login(address, password)
    mailbox.select("INBOX", readonly=True)
    return mailbox


def _fetch(mailbox: imaplib.IMAP4_SSL, uid: bytes) -> Header | None:
    """One message's header block, or None when it cannot be read.

    One unreadable message is not worth failing a question over, so it is dropped and the
    rest are answered with.
    """
    status, data = mailbox.uid("FETCH", uid.decode(), FETCH)
    if status != "OK" or not data or not isinstance(data[0], tuple):
        return None

    parsed = email.message_from_bytes(data[0][1])
    return Header(
        sender=_decode(parsed.get("From")),
        subject=_decode(parsed.get("Subject")) or "(no subject)",
        sent_at=_sent_at(parsed.get("Date")),
        link=PERMALINK.format(uid=uid.decode()),
    )


def _decode(raw: str | None) -> str:
    """A header as text. Non-ASCII arrives RFC 2047-encoded and reads as mojibake raw."""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except (UnicodeDecodeError, LookupError, ValueError):
        return raw


def _sent_at(raw: str | None) -> datetime | None:
    """The Date header as an aware datetime, or None when it is missing or malformed.

    A message with no usable date is kept rather than dropped: it arrived in the window
    the search selected, and hiding it would be a silent omission.
    """
    if not raw:
        return None
    parsed = email.utils.parsedate_to_datetime(raw)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
