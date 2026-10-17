"""Agent that analyzes gold figures and returns cited numbers; may draft Jira writes."""

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset

from mycel.agents.core.base import BaseAgent
from mycel.agents.core.deps import MycelDeps
from mycel.agents.prompts import load
from mycel.agents.tools import compute, jira, query, work


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
    findings: list[str] = Field(
        description="What the figures show, one short statement each; only what was asked."
    )
    caveats: list[str] = Field(
        default_factory=list,
        description="Anything that limits the reading: missing data, undefined results.",
    )


#: Reads whose rows are already the answer.
READY_READS = frozenset({"hours_by_person", "late_items", "open_epics"})


def unanswered(ctx: RunContext[MycelDeps], _: ToolDefinition) -> bool:
    """False once a ready read returned: weaker models re-check it call by call otherwise."""
    return not any(
        isinstance(part, ToolReturnPart) and part.tool_name in READY_READS
        for message in ctx.messages
        for part in message.parts
    )


class Analyst(BaseAgent[Analysis]):
    name = "analyst"
    instructions = load("analyst")
    output_type = Analysis

    @classmethod
    def toolsets(cls) -> list[AbstractToolset[MycelDeps]]:
        sets: list[AbstractToolset[MycelDeps]] = [
            work.build_toolset(),
            compute.build_toolset().filtered(unanswered),
            query.build_toolset().filtered(unanswered),
        ]
        if jira.offered():
            sets.append(jira.build_toolset())
        return sets

    @classmethod
    def validate_output(cls, ctx: RunContext[MycelDeps], output: Analysis) -> Analysis:
        """Reject figures with no source."""
        uncited = [f.label for f in output.figures if not f.source.strip()]
        if uncited:
            raise ModelRetry(
                "These figures have no source: "
                + ", ".join(repr(label) for label in uncited)
                + ". Give each one the tool call or input field it came from."
            )
        return output
