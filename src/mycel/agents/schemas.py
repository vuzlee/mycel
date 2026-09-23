"""Agent output schemas, importable from outside `agents/`.

A schema named across a layer boundary belongs here rather than beside the agent that
produces it: reaching into `agents/agent/summariser.py` to borrow one would make the
borrowing layer depend on where an agent module happens to live. An output type nothing
outside its own agent ever names stays beside that agent, next to the prompt that produces
it.

The orchestrator is no longer here. Its output became markdown in batch 033 — a chatbot
answers in whatever shape the question deserves, and `Report{findings, gaps}` forced every
answer into one list. A `str` needs no schema, which is why this module now describes only
the summariser's rows.
"""

from typing import Literal

from pydantic import BaseModel, Field


class WorkLine(BaseModel):
    """One ticket, as a row rather than a sentence.

    Columns, not prose: a list of strings makes every renderer parse the model's sentence
    back apart, and they disagree about how. `note` is the only free text, and it is the
    only part that is a judgement.
    """

    key: str = Field(description="The issue key alone, e.g. 'MYC-14'. Never with the title.")
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
    """One person's estimated against spent, already in man-days.

    Every figure is copied from what the prompt was given. The model chooses who is worth
    a `note`, not what the numbers are.
    """

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
    """What a team did over one window, in rows.

    Rows rather than prose, because a standup answers a fixed set of questions and a
    paragraph makes the reader find them. `at_risk` is the one the meeting exists for, so
    it is a field of its own rather than a sentence somewhere in the middle.

    The lists became structured in batch 024. They were `list[str]`, which meant the model
    wrote "MYC-14 — Work dashboard (E2) — vu le" and every surface that wanted a table had
    to take that sentence apart again. A column the model fills is a column a renderer can
    align.

    Still rows even though the orchestrator now answers in markdown: this is what the
    summariser hands *up*, and a table the orchestrator was given as columns is a table it
    can lay out. Flattening here would make it re-derive the columns from prose.
    """

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
