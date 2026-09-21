"""Agent that analyses figures from gold: trends, anomalies, period-over-period.

Returns numbers with their sources, not prose — framing them is someone else's job.

"With their sources" is enforced, not requested: `Analyst.validate_output` rejects any
figure whose `source` is empty and re-prompts naming the offending labels. Without it
nothing downstream can check a draft against the figures, and the report becomes a set of
assertions that cannot be cited.

Arithmetic goes through `tools/compute.py` rather than the model's head, because an
arithmetic slip is the hardest error to spot in a finished report: a wrong number reads
exactly like a right one. That module owns the tools themselves; this file only says which
toolsets the analyst gets.

`tools/query.py` is the gold-layer read this file promised when it only had `compute`, and
it is what makes the dashboard an agent rather than a second screen: the questions a fixed
set of SQL queries could not answer are now written per question. It needs no new rule to
stay honest — `validate_output` already refuses a figure without a source, and the query
that produced a number *is* its source.
"""

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.toolsets import AbstractToolset

from mycel.agents.core.base import BaseAgent
from mycel.agents.core.deps import MycelDeps
from mycel.agents.prompts import load
from mycel.agents.tools import compute, query


class Figure(BaseModel):
    """One number, with where it came from."""

    label: str = Field(description="What this number measures, in a few words.")
    value: float
    unit: str | None = Field(
        default=None, description="'%', 'USD', 'users'. Null when the value is a bare count."
    )
    source: str = Field(
        description=(
            "Where this number came from: the tool call that produced it, or the input "
            "field it was read from. Never leave this empty."
        )
    )


class Analysis(BaseModel):
    """What the analyst hands back."""

    figures: list[Figure] = Field(description="Every number referenced in the findings.")
    findings: list[str] = Field(description="What the figures show, one statement each.")
    caveats: list[str] = Field(
        default_factory=list,
        description="Anything that limits the reading: missing data, undefined results.",
    )


class Analyst(BaseAgent[Analysis]):
    """Reads figures, reports what they show, cites every number."""

    name = "analyst"
    instructions = load("analyst")
    output_type = Analysis

    @classmethod
    def toolsets(cls) -> list[AbstractToolset[MycelDeps]]:
        return [compute.build_toolset(), query.build_toolset()]

    @classmethod
    def validate_output(cls, ctx: RunContext[MycelDeps], output: Analysis) -> Analysis:
        """Reject uncited figures. This is the enforcement of the module docstring."""
        uncited = [f.label for f in output.figures if not f.source.strip()]
        if uncited:
            raise ModelRetry(
                "These figures have no source: "
                + ", ".join(repr(label) for label in uncited)
                + ". Give each one the tool call or input field it came from."
            )
        return output
