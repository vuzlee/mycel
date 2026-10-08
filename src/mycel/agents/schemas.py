"""Agent output schemas named outside `agents/`."""

from typing import Literal

from pydantic import BaseModel, Field


class WorkLine(BaseModel):
    """One ticket, as a row rather than a sentence."""

    key: str = Field(description="The issue key alone, e.g. 'PROJ-14'. Never with the title.")
    title: str = Field(description="The ticket's own title, shortened but not reworded.")
    who: str = Field(default="", description="Who it is on. Empty when nobody is assigned.")
    epic: str = Field(default="", description="The epic above it, by name. Empty if none.")
    estimated: str = Field(
        default="", description="Its estimate, copied with its unit, e.g. '2.0d'. Empty if none."
    )
    spent: str = Field(
        default="", description="Time spent on it, copied with its unit. Empty if none."
    )
    due: str = Field(
        default="",
        description="Its due date as the data gives it, e.g. '2026-09-30'. Empty if none.",
    )
    note: str = Field(
        default="",
        description=(
            "Why this line matters, when it does — 'four days past due', 'over estimate by "
            "3d'. A few words. Empty when the row speaks for itself, which is most of the "
            "time for shipped and in-flight work."
        ),
    )


class LoadLine(BaseModel):
    """One person's estimated against spent, in man-days, copied from the prompt."""

    person: str = Field(description="Their display name, as the tracker spells it.")
    items: int = Field(default=0, description="How many tickets they carried in the window.")
    done: int = Field(default=0, description="How many of those are finished.")
    estimated: str = Field(default="", description="Estimated, copied with its unit, e.g. '38.6d'.")
    spent: str = Field(default="", description="Spent, copied with its unit, e.g. '11.8d'.")
    note: str = Field(
        default="",
        description="Only when it is worth saying — 'over by 4d'. Empty for everyone else.",
    )


class ProgressSummary(BaseModel):
    """What a team did over one window, in rows."""

    period: str = Field(description="The window in plain words, e.g. '15-21 September 2026'.")
    headline: str = Field(
        default="",
        description=(
            "The whole window in one sentence, under 140 characters: what moved and the "
            "one thing that needs attention. Read on its own by someone who opens nothing "
            "else, so it never refers to 'the below' or 'the following'."
        ),
    )
    health: Literal["on_track", "at_risk", "off_track"] = Field(
        default="on_track",
        description=(
            "The window's verdict. `on_track` nothing overdue and no one far over "
            "estimate; `at_risk` something is late or over but the work is moving; "
            "`off_track` most of what was due did not land. Judged, not computed."
        ),
    )
    shipped: list[WorkLine] = Field(
        default_factory=list, description="What was finished in the window."
    )
    in_flight: list[WorkLine] = Field(
        default_factory=list, description="What is underway at the end of the window."
    )
    at_risk: list[WorkLine] = Field(
        default_factory=list,
        description=(
            "What is late or about to be: past its due date and not done, or well over "
            "its estimate. Most urgent first, and every row carries a `note` saying which. "
            "Never merged into the others."
        ),
    )
    load: list[LoadLine] = Field(
        default_factory=list, description="One row per person, estimated against spent."
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Limits on the summary itself, e.g. that the window was truncated.",
    )
