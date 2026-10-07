"""Chips: the sources a person picks for one turn. No chip, no tool.

A chip is enforced by what the model is shown, not by what it is told. Every toolset an
agent builds goes through `allowed`, which reads `deps.chips`; a tool outside the chosen
chips is never in the request, so the model cannot call it.

`chips=None` means "not decided by a person" — a script, a test, a scheduled report —
and keeps every tool. An empty set is a person who picked nothing, and gets none.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.tools import ToolDefinition


#: What each chip reaches, as the person reads it in a "turn this on" reply.
REACHES: dict[str, str] = {
    "jira": "your team's Jira",
    "mail": "your mail",
    "calendar": "your calendar",
    "web": "the web",
}


def missing_sources_note(chips: "frozenset[Chip] | None") -> str:
    """This turn's note to the orchestrator: which sources are off, and what to say then.

    Without it a run with no tools writes a heading and stops, and the page shows a title
    over nothing.
    """
    if chips is None:
        return ""
    off = [label for key, label in REACHES.items() if key not in chips]
    if not off:
        return ""
    return (
        f"Switched off for this turn: {', '.join(off)}. If the question needs one of them, "
        "call nothing and write no heading. Reply in one or two sentences: name the source "
        "it needs, say it is switched off, and that it can be turned on from the sources "
        "button next to the question box. If an agent reports that an account is not "
        "connected, say so, and that it can be connected under Settings → Accounts."
    )


class Chip(StrEnum):
    KNOWLEDGE = "knowledge"
    WEB = "web"
    JIRA = "jira"
    CALENDAR = "calendar"
    MAIL = "mail"


#: Which tools each chip opens, at every level: the specialist an orchestrator may call,
#: and the tools that specialist may then use. Knowledge is absent: it opens no tool, its
#: passages are put in the prompt by `domains/knowledge.py`.
TOOLS: dict[Chip, frozenset[str]] = {
    Chip.WEB: frozenset({"researcher", "web_search"}),
    Chip.MAIL: frozenset({"researcher", "read_mail"}),
    Chip.CALENDAR: frozenset({"researcher", "read_events", "draft_event", "confirm_event"}),
    Chip.JIRA: frozenset(
        {
            "analyst",
            "summariser",
            "run_sql",
            "find_jira_user",
            "draft_jira_write",
            "confirm_jira_write",
            "percent_change",
            "absolute_change",
            "percentage",
            "cagr",
            "share_of_total",
            "summary_stats",
        }
    ),
}


def parse(raw: Any) -> frozenset[Chip] | None:
    """Chips from a job payload. Unknown names are dropped, not trusted."""
    if raw is None:
        return None
    return frozenset(Chip(c) for c in raw if c in Chip._value2member_map_)


def tools_for(chips: frozenset[Chip]) -> frozenset[str]:
    return frozenset().union(*(TOOLS.get(c, frozenset()) for c in chips))


def allowed(ctx: "RunContext[Any]", tool: "ToolDefinition") -> bool:
    """The filter every toolset passes through."""
    chips = getattr(ctx.deps, "chips", None)
    return chips is None or tool.name in tools_for(chips)
