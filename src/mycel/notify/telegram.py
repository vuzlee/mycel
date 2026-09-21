"""Send a finished summary to Telegram. One call, one direction.

The bot no longer reads anything — `getUpdates` and the hashtag convention went in batch
016 — so this shares nothing with the old connector but a token. A thing we push to and a
thing we pulled from are not the same module wearing a different method.

What goes out is the headline and a link, not the report. A full report in a chat bubble
is a report nobody scrolls, and the link opens the one place it is readable.

Fire and forget: every failure is logged and none is raised. The report was produced and
written to both stores before this runs, and losing the job over an unreachable chat would
be throwing away the work to report that the receipt did not arrive.
"""

import httpx2

from mycel.agents.schemas import ProgressSummary
from mycel.core.config import get_settings
from mycel.core.logging import get_logger

HTTP_TIMEOUT_S = 10.0

#: Telegram rejects a message over 4096 characters outright. Well under it, because a
#: notification that needs scrolling has already failed at being one.
MAX_CHARS = 600

#: The verdict as one character. A chat notification is read at a glance in a list of
#: other notifications, and a word that has to be parsed is a word that gets scrolled past.
VERDICT = {"on_track": "🟢", "at_risk": "🟡", "off_track": "🔴"}

log = get_logger(__name__)


async def notify_summary(job_id: str, project: str, summary: ProgressSummary) -> bool:
    """Tell the chat a summary is ready. True if it was sent, False for every other case.

    Not configured is a normal state, not a failure: a deployment that notifies nobody is
    one this returns False for and logs at debug, so a missing token never fills a log
    with warnings a nobody asked for.
    """
    settings = get_settings()
    token = settings.telegram_bot_token
    chat_id = settings.telegram_notify_chat_id
    if token is None or not chat_id:
        log.debug("telegram notify not configured", extra={"job_id": job_id})
        return False

    url = f"https://api.telegram.org/bot{token.get_secret_value()}/sendMessage"
    body = {
        "chat_id": chat_id,
        "text": headline(project, summary, _link(job_id)),
        "disable_web_page_preview": True,
    }

    try:
        async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            response = await client.post(url, json=body)
        response.raise_for_status()
    except httpx2.HTTPError as exc:
        log.warning("telegram notify failed", extra={"job_id": job_id, "error": str(exc)})
        return False

    log.info("telegram notified", extra={"job_id": job_id, "chat_id": chat_id})
    return True


def headline(project: str, summary: ProgressSummary, link: str) -> str:
    """The message itself: what the window was, what is late, and where to read the rest.

    The summary's own headline leads, because it is the one line written to be read alone.
    The counts follow it as the evidence, and at risk is the only list quoted — one line of
    it, the one a person has to act on today. The rest is a record, and the record is
    behind the link.
    """
    lines = [f"{VERDICT[summary.health]} {project} — {summary.period}"]
    if summary.headline:
        lines.append(summary.headline)
    lines.append(
        f"{len(summary.shipped)} shipped · {len(summary.in_flight)} in flight · "
        f"{len(summary.at_risk)} at risk"
    )
    if summary.at_risk:
        worst = summary.at_risk[0]
        why = f" — {worst.note}" if worst.note else ""
        lines.append(f"⚠ {worst.key} {worst.title}{why}")
    lines.append(link)

    text = "\n".join(lines)
    return text if len(text) <= MAX_CHARS else f"{text[: MAX_CHARS - 1]}…"


def _link(job_id: str) -> str:
    """Where the whole report is. Absolute, because a chat has no page to be relative to."""
    return f"{get_settings().public_base_url.rstrip('/')}/app/reports?job={job_id}"
