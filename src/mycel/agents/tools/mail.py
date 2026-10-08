"""Tool: read the headers of the asker's recent mail."""

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ToolFailed
from mycel.agents.core.guards import guard_repeat
from mycel.agents.tools.limits import MAX_HOURS
from mycel.core.logging import get_logger
from mycel.services.google_oauth import NotConnected, token_for
from mycel.sources import SourceError, gmail

log = get_logger(__name__)


#: Newest first, so the cap drops the oldest.
MAX_MESSAGES = 60


CONNECT = (
    "No Google account is connected, or it has not allowed Mycel to read mail. Open the "
    "account menu, choose Settings, and connect Google — then ask again."
)


def build_toolset() -> FunctionToolset[MycelDeps]:
    toolset: FunctionToolset[MycelDeps] = FunctionToolset()

    @toolset.tool(name="read_mail")
    async def _read_mail(ctx: RunContext[MycelDeps], hours: int = 24) -> str:
        """Read the sender, subject and date of the asker's own recent messages.

        Message bodies are never read, so judge only from sender and subject — and say
        when that is not enough to be sure. Every line carries a link; cite it.

        Args:
            hours: How far back to look. Today is 24, this week 168, this month 720,
                which is also the most that can be asked for.
        """
        guard_repeat(ctx, "read_mail", threshold=ctx.deps.settings.repeat_threshold, hours=hours)

        if hours < 1:
            raise ModelRetry("read_mail needs a window of at least one hour.")

        if ctx.deps.principal is None:
            return CONNECT
        capped = min(hours, MAX_HOURS)
        try:
            token = await token_for(ctx.deps.principal.id)
            mailbox = await gmail.read_recent(token, capped, MAX_MESSAGES)
        except NotConnected:
            return CONNECT
        except SourceError as exc:
            raise ToolFailed("read_mail", str(exc)) from exc

        return _render(mailbox, asked=hours, capped=capped)

    return toolset


def _render(mailbox: gmail.Mailbox, asked: int, capped: int) -> str:
    """The mailbox as quotable text, counts first so the model does not invent them."""
    lines = [f"{mailbox.total} messages in the last {capped} hours."]
    if capped < asked:
        lines.append(f"({asked} hours was asked for; {MAX_HOURS} is the most that can be read.)")
    if not mailbox.headers:
        lines.append("(no messages)")
        return "\n".join(lines)

    lines.append(
        f"Showing {len(mailbox.headers)}, newest first. Columns: date | from | subject | link"
    )
    for header in mailbox.headers:
        sent = header.sent_at.strftime("%Y-%m-%d %H:%M") if header.sent_at else "(no date)"
        lines.append(f"{sent} | {header.sender} | {header.subject} | {header.link}")
    return "\n".join(lines)
