"""Agent that analyses figures from gold: trends, anomalies, period-over-period.

Returns numbers with their sources, not prose — framing them is someone else's job.

"With their sources" is enforced, not requested: `_every_figure_is_sourced` rejects any
figure whose `source` is empty and re-prompts naming the offending labels. Without it
nothing downstream can check a draft against the figures, and the report becomes a set of
assertions that cannot be cited.

Arithmetic goes through `tools/compute.py` rather than the model's head, because an
arithmetic slip is the hardest error to spot in a finished report: a wrong number reads
exactly like a right one. That module owns the tools themselves; this file only says which
toolsets the analyst gets.

This slice computes over figures given in the prompt. A gold-layer query tool joins the
toolset when `storage/` lands — the agent shape does not change when it does.
"""

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.tools import compute

ANALYST_SETTINGS = AgentSettings(model_spec="cloud:claude-sonnet-5")

INSTRUCTIONS = """\
You analyse figures and report what they show. You do not write prose for publication.

Rules:
- Use the compute tools for every calculation. Do not do arithmetic yourself, even when
  it looks trivial.
- Every figure you report must carry a source saying where it came from: the tool call
  that produced it, or the part of the input it was given in.
- If a calculation is undefined, say so and report what can be said instead. Never
  substitute a plausible-looking number.
- State what the figures show. Leave interpretation and framing to the caller.
"""


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


def build_analyst(
    settings: AgentSettings | None = None,
) -> Agent[MycelDeps, Analysis]:
    """Build the analyst.

    A factory rather than a module-level singleton, so tests can build one per model
    without a global to reset, and `registry.py` decides the model spec at startup.

    **No model is built here.** `run_agent` resolves the spec and passes the model per
    run, so constructing an agent needs no credentials — the registry can be imported,
    listed and unit-tested on a machine with no API key, and a missing key fails when a
    run is actually attempted rather than at import time.
    """
    cfg = settings or ANALYST_SETTINGS
    agent: Agent[MycelDeps, Analysis] = Agent(
        deps_type=MycelDeps,
        output_type=Analysis,
        instructions=INSTRUCTIONS,
        retries=cfg.tool_retries,
        name="analyst",
        toolsets=[compute.build_toolset()],
    )
    _register_output_validator(agent)
    return agent


def _register_output_validator(agent: Agent[MycelDeps, Analysis]) -> None:
    @agent.output_validator
    def _every_figure_is_sourced(ctx: RunContext[MycelDeps], output: Analysis) -> Analysis:
        """Reject uncited figures. This is the enforcement of the module docstring."""
        uncited = [f.label for f in output.figures if not f.source.strip()]
        if uncited:
            raise ModelRetry(
                "These figures have no source: "
                + ", ".join(repr(label) for label in uncited)
                + ". Give each one the tool call or input field it came from."
            )
        return output
