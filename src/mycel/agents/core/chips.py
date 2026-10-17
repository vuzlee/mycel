"""Chips: the sources a person picks for one turn. A tool outside them is never sent.

`chips=None` keeps every tool; an empty set keeps none.
"""

from typing import TYPE_CHECKING, Any

from mycel.core.chips import Chip

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
    """Instructions telling the orchestrator which sources are off and how to reply."""
    if chips is None:
        return ""
    on = [label for key, label in REACHES.items() if key in chips]
    off = [label for key, label in REACHES.items() if key not in chips]
    # An earlier turn may have said a source was off; this turn's chips are what count.
    note = (
        f"Switched on for this turn: {', '.join(on)}. A question that needs one of these "
        "goes to the agent that covers it; call it. Never say a switched-on source is off "
        "or not connected unless that agent has just said so in this turn, whatever "
        "earlier answers in this conversation said. "
        if on
        else ""
    )
    if not off:
        return note.strip()
    return note + (
        f"Switched off for this turn: {', '.join(off)}. If the question needs one of them, "
        "call nothing and write no heading. Reply in one or two sentences: name the source "
        "it needs, say it is switched off, and that it can be turned on from the sources "
        "button next to the question box. If an agent reports that an account is not "
        "connected, say so, and that it can be connected under Settings → Accounts."
    )


#: Where a tool says which chips open it: `metadata=opens(Chip.JIRA)` on its toolset.
CHIPS_KEY = "chips"


def opens(*chips: Chip) -> dict[str, Any]:
    """Tool metadata naming the chips that open it. Knowledge opens no tool."""
    return {CHIPS_KEY: frozenset(chips)}


def parse(raw: Any) -> frozenset[Chip] | None:
    """Chips from a job payload. Unknown names are dropped, not trusted."""
    if raw is None:
        return None
    return frozenset(Chip(c) for c in raw if c in Chip._value2member_map_)


def allowed(ctx: "RunContext[Any]", tool: "ToolDefinition") -> bool:
    """The filter every toolset passes through. A tool that names no chip is never offered."""
    chips = getattr(ctx.deps, "chips", None)
    if chips is None:
        return True
    return bool(chips & (tool.metadata or {}).get(CHIPS_KEY, frozenset()))
