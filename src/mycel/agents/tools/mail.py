"""One tool: read the mailbox over the window the question implies.

The old plan for this was a bulletin on a cron at 08:00, with a fixed "yesterday" window.
Two things were wrong with it. It spent one of twenty daily model requests whether or not
anyone read the result, and a fixed window cannot answer the most natural question there
is about mail — *anything important this week?*

So the window is a parameter and the model fills it in: today is 24 hours, this week is
168, this month is 720. That is the same shape as the `summariser` tool taking `days`, and
for the same reason — a span is something a model reads out of a sentence and code cannot.

**This needs no new rule to stay honest.** `Researcher.validate_output` has rejected any
claim with empty `sources` since the first slice, and every Gmail message has a permalink,
so the existing rule already covers what comes back here. The same argument let `run_sql`
join the analyst without new machinery.

Headers only, and why, is `sources/gmail.py`. This file is the window, the cap, and the
shape the model reads.
"""

import asyncio

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ToolFailed
from mycel.agents.core.guards import guard_repeat
from mycel.core.logging import get_logger
from mycel.sources import SourceError, gmail

log = get_logger(__name__)

#: A month. Not a permission — headers cross the context window, and a year of them is
#: cost rather than information. Asking for more is answered with this much and told so.
MAX_HOURS = 720

#: Newest first, so the cap drops the oldest rather than the most likely to matter.
MAX_MESSAGES = 60


def build_toolset() -> FunctionToolset[MycelDeps]:
    """Reading the mailbox, as a toolset an agent can be given."""
    toolset: FunctionToolset[MycelDeps] = FunctionToolset()

    @toolset.tool(name="read_mail")
    async def _read_mail(ctx: RunContext[MycelDeps], hours: int = 24) -> str:
        """Read the sender, subject and date of messages received recently.

        Message bodies are never read, so judge only from sender and subject — and say
        when that is not enough to be sure. Every line carries a link; cite it.

        Args:
            hours: How far back to look. Today is 24, this week 168, this month 720,
                which is also the most that can be asked for.
        """
        guard_repeat(ctx, "read_mail", threshold=ctx.deps.settings.repeat_threshold, hours=hours)

        if hours < 1:
            raise ModelRetry("read_mail needs a window of at least one hour.")

        capped = min(hours, MAX_HOURS)
        try:
            mailbox = await asyncio.to_thread(gmail.read_recent, capped, MAX_MESSAGES)
        except SourceError as exc:
            # Not the model's to fix: no credentials, or a mailbox that will not answer.
            # Re-prompting would walk it round the same loop until the run dies unread.
            raise ToolFailed("read_mail", str(exc)) from exc

        return _render(mailbox, asked=hours, capped=capped)

    return toolset


def _render(mailbox: gmail.Mailbox, asked: int, capped: int) -> str:
    """The mailbox as text the model can quote from, counts first.

    The counts lead because they are the part the model must not invent: how many messages
    were looked at is the difference between "three worth reading" and "three of forty-seven".
    """
    lines = [f"{mailbox.total} messages in the last {capped} hours."]
    if capped < asked:
        lines.append(f"({asked} hours was asked for; {MAX_HOURS} is the most that can be read.)")
    if not mailbox.headers:
        lines.append("(no messages)")
        return "\n".join(lines)

    lines.append(
        f"Showing {len(mailbox.headers)}, newest first. "
        "Columns: date | from | subject | link"
    )
    for header in mailbox.headers:
        sent = header.sent_at.strftime("%Y-%m-%d %H:%M") if header.sent_at else "(no date)"
        lines.append(f"{sent} | {header.sender} | {header.subject} | {header.link}")
    return "\n".join(lines)
