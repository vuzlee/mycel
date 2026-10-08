"""Calendar tools: read events, draft one, and book it only after the person agrees.

No principal reads nothing; an unconnected account gets a "connect" sentence, not an error.
"""

from datetime import datetime, timedelta

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ToolFailed
from mycel.agents.core.guards import guard_repeat
from mycel.agents.tools.limits import MAX_HOURS
from mycel.core.logging import get_logger
from mycel.infra.redis import drafts
from mycel.services.google_oauth import GoogleError, NotConnected
from mycel.sources import google_calendar

log = get_logger(__name__)


#: A working day; longer is likely a misread duration.
MAX_MINUTES = 480

CONNECT = (
    "No Google account is connected. Open the account menu, choose Settings, and connect "
    "one — then ask again. Nothing about the calendar can be answered until then."
)


def build_toolset() -> FunctionToolset[MycelDeps]:
    toolset: FunctionToolset[MycelDeps] = FunctionToolset()
    toolset.add_function(_read_events, name="read_events")
    toolset.add_function(_draft_event, name="draft_event")
    toolset.add_function(_confirm_event, name="confirm_event")
    return toolset


async def _read_events(ctx: RunContext[MycelDeps], hours: int = 12) -> str:
    """Read what is on the asker's own calendar over the hours ahead.

    Use it for any question about their time: what is on today, what this week looks
    like, when they are free. Free time is not a separate tool — read the list and say
    which gaps are free.

    Args:
        hours: How far ahead to look. This afternoon is 12, today 24, this week 168,
            this month 720, which is also the most that can be asked for.
    """
    guard_repeat(ctx, "read_events", hours=hours)
    if hours < 1:
        raise ModelRetry("read_events needs a window of at least one hour.")

    user_id = _whose(ctx.deps)
    if user_id is None:
        return CONNECT

    capped = min(hours, MAX_HOURS)
    try:
        events = await google_calendar.list_events(user_id, capped)
    except NotConnected:
        return CONNECT
    except GoogleError as exc:
        raise ToolFailed("read_events", str(exc)) from exc
    return _render(events, asked=hours, capped=capped)


async def _draft_event(
    ctx: RunContext[MycelDeps], summary: str, starts_at: str, minutes: int = 30
) -> str:
    """Work out an event and read it back. **This writes nothing to the calendar.**

    Show the person the sentence this returns, in full, and wait for them to agree. Only
    then call `confirm_event` with the draft id. If they correct the time, draft again.

    Args:
        summary: What the event is called, in the words they used.
        starts_at: When it starts, as `YYYY-MM-DDTHH:MM` in the team's own timezone.
            No offset and no `Z` — the timezone is added here.
        minutes: How long it lasts. Thirty unless they said otherwise.
    """
    guard_repeat(
        ctx,
        "draft_event",
        summary=summary,
        starts_at=starts_at,
    )
    user_id = _whose(ctx.deps)
    if user_id is None:
        return CONNECT

    if not 1 <= minutes <= MAX_MINUTES:
        raise ModelRetry(f"minutes must be between 1 and {MAX_MINUTES}.")
    starts = _parse(starts_at)
    ends = starts + timedelta(minutes=minutes)

    draft = await drafts.put(user_id, summary.strip(), starts, ends)
    return (
        f"Not booked yet. {_spell(starts)} to {ends.strftime('%H:%M')}, "
        f"{minutes} minutes — {draft.summary}.\n"
        f"Read that back and ask whether it is right. To book it, call confirm_event "
        f"with draft_id={draft.draft_id}."
    )


async def _confirm_event(ctx: RunContext[MycelDeps], draft_id: str) -> str:
    """Book a drafted event. Call this only after the person has agreed to it.

    Args:
        draft_id: The id `draft_event` returned for the event they agreed to.
    """
    user_id = _whose(ctx.deps)
    if user_id is None:
        return CONNECT

    draft = await drafts.take(draft_id, user_id)
    if draft is None:
        # Not a retry: the draft is gone and no argument can fix that.
        return (
            "That draft has expired or was already booked. Nothing was written. "
            "Draft the event again if they still want it."
        )

    try:
        event = await google_calendar.create_event(
            user_id, draft.summary, draft.starts_at, draft.ends_at
        )
    except NotConnected:
        return CONNECT
    except GoogleError as exc:
        raise ToolFailed("confirm_event", str(exc)) from exc

    log.info("calendar event created", extra={"user_id": user_id})
    return f"Booked: {_spell(event.starts_at)} — {event.summary}. {event.link}"


def _whose(deps: MycelDeps) -> int | None:
    """Whose calendar this run may touch, or `None` for a run nobody is behind."""
    return deps.principal.id if deps.principal else None


def _parse(starts_at: str) -> datetime:
    """Parse the model's time in the team's zone; refuse the past (naming today) or >1 year out."""
    try:
        moment = datetime.fromisoformat(starts_at)
    except ValueError:
        raise ModelRetry(
            "starts_at must look like 2026-09-26T15:00, in the team's own timezone."
        ) from None

    zone = google_calendar.zone()
    moment = moment.replace(tzinfo=zone) if moment.tzinfo is None else moment.astimezone(zone)
    now = datetime.now(zone)
    if moment < now:
        raise ModelRetry(
            f"{starts_at} is in the past. It is {now.strftime('%A %d %B %Y, %H:%M')} "
            f"in {google_calendar.zone_name()} — work the date out from that and draft again."
        )
    if moment > now + timedelta(days=365):
        raise ModelRetry(f"{starts_at} is more than a year away; check the year.")
    return moment


def _spell(moment: datetime) -> str:
    """A time in words, so a wrong day is easy for the person to catch."""
    return moment.strftime("%A %d %B %Y, %H:%M")


def _render(events: list[google_calendar.Event], asked: int, capped: int) -> str:
    """The calendar as quotable text, count first so the model does not invent it."""
    lines = [
        f"{len(events)} events in the next {capped} hours, times in {google_calendar.zone_name()}."
    ]
    if capped < asked:
        lines.append(f"({asked} hours was asked for; {MAX_HOURS} is the most that can be read.)")
    if not events:
        lines.append("(nothing on the calendar)")
        return "\n".join(lines)

    lines.append("Columns: when | what | link")
    for event in events:
        when = (
            f"{event.starts_at:%a %d %b} (all day)"
            if event.all_day
            else f"{event.starts_at:%a %d %b %H:%M}-{event.ends_at:%H:%M}"
        )
        lines.append(f"{when} | {event.summary} | {event.link}")
    return "\n".join(lines)
