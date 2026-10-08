"""Agent that reads the web, mail, calendar and documents, and cites every claim."""

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.toolsets import AbstractToolset

from mycel.agents.core.base import BaseAgent
from mycel.agents.core.deps import MycelDeps
from mycel.agents.prompts import load
from mycel.agents.tools import calendar, mail, rag_search, web_search
from mycel.infra.vectors.client import configured as vectors_configured


class Claim(BaseModel):
    """One statement about the world, with where it was read."""

    statement: str = Field(description="One thing that is true, stated plainly.")
    sources: list[str] = Field(
        description=(
            "Urls of the pages this statement came from, at least one. Never leave empty: "
            "a claim without a source cannot be checked and does not belong in a report."
        )
    )
    as_of: str | None = Field(
        default=None,
        description="When the sources were published, YYYY-MM-DD, if they say. Null when "
        "undated — which means unknown age, not current.",
    )


class Research(BaseModel):
    """What the researcher hands back."""

    claims: list[Claim] = Field(description="What the sources say, one statement each.")
    contested: list[str] = Field(
        default_factory=list,
        description="Points where sources disagreed, described rather than resolved.",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="What was asked but could not be found. An empty search is a finding.",
    )


class Researcher(BaseAgent[Research]):
    name = "researcher"
    instructions = load("researcher")
    output_type = Research

    @classmethod
    def toolsets(cls) -> list[AbstractToolset[MycelDeps]]:
        sets: list[AbstractToolset[MycelDeps]] = [
            web_search.build_toolset(),
            mail.build_toolset(),
            calendar.build_toolset(),
        ]
        # A visible tool gets called; one with nothing behind it wastes a turn.
        if vectors_configured():
            sets.append(rag_search.build_toolset())
        return sets

    @classmethod
    def validate_output(cls, ctx: RunContext[MycelDeps], output: Research) -> Research:
        """Reject claims with no source."""
        uncited = [c.statement for c in output.claims if not [s for s in c.sources if s.strip()]]
        if uncited:
            raise ModelRetry(
                "These claims have no source: "
                + ", ".join(repr(statement) for statement in uncited)
                + ". Give each one the url it came from, or drop it."
            )
        return output
