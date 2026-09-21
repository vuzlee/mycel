"""Agent that finds out what is currently true about a topic, and cites where it read it.

The counterpart to the analyst: that one reasons over figures it is given, this one goes
and gets what the prompt does not contain. Both hand back statements with sources and
neither writes prose, which is what lets the orchestrator treat them interchangeably.

**Sources are enforced, not requested.** `validate_output` rejects any claim whose `sources`
list is empty and re-prompts naming it. Without that the agent degrades into answering from
the model's own memory — fluent, undated, and indistinguishable from a search result until
someone checks. The tool cannot prevent this on its own: it can only guarantee that what it
*returns* carries urls, not that the model used them.

**The mailbox is outside this system too.** `tools/mail.py` joined the toolset for the
same reason `web_search` is here: both fetch what the prompt does not contain, and both
fail the same way when the model answers from memory instead. The enforcement above needs
no change to cover them — every Gmail message has a permalink, so a claim about mail has a
source in exactly the sense `validate_output` already means.

Searching is `tools/web_search.py`, reading mail is `tools/mail.py`; this file only says
which toolsets the researcher gets.
"""

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.toolsets import AbstractToolset

from mycel.agents.core.base import BaseAgent
from mycel.agents.core.deps import MycelDeps
from mycel.agents.prompts import load
from mycel.agents.tools import mail, web_search


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
    """Searches the web, reports what it says, cites every claim."""

    name = "researcher"
    instructions = load("researcher")
    output_type = Research

    @classmethod
    def toolsets(cls) -> list[AbstractToolset[MycelDeps]]:
        return [web_search.build_toolset(), mail.build_toolset()]

    @classmethod
    def validate_output(cls, ctx: RunContext[MycelDeps], output: Research) -> Research:
        """Reject uncited claims. This is the enforcement of the module docstring."""
        uncited = [c.statement for c in output.claims if not [s for s in c.sources if s.strip()]]
        if uncited:
            raise ModelRetry(
                "These claims have no source: "
                + ", ".join(repr(statement) for statement in uncited)
                + ". Give each one the url it came from, or drop it."
            )
        return output
