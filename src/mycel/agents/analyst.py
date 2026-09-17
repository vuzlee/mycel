"""Agent that analyses figures from gold: trends, anomalies, period-over-period.

Returns numbers with their sources, not prose — the writing is `writer.py`'s job.

"With their sources" is enforced, not requested: `_every_figure_is_sourced` rejects any
figure whose `source` is empty and re-prompts naming the offending labels. Without it
`reviewer.py` has nothing to check a draft against, and the report becomes a set of
assertions that cannot be cited.

Arithmetic goes through `tools/compute.py` rather than the model's head, because an
arithmetic slip is the hardest error to spot in a finished report: a wrong number reads
exactly like a right one.

This slice computes over figures given in the prompt. `query_gold` joins the toolset when
`storage/` lands — the agent shape does not change when it does.
"""

from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.guards import guard_repeat
from mycel.agents.tools import compute
from mycel.agents.tools.compute import SummaryStats

T = TypeVar("T")

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
- State what the figures show. Leave interpretation and framing to the writer.
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
    """What the analyst hands to the writer."""

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
    )
    _register_tools(agent)
    return agent


def _register_tools(agent: Agent[MycelDeps, Analysis]) -> None:
    """Wrap the pure functions in `compute.py` as tools.

    Each wrapper does the same three things: check for a degenerate loop, call the pure
    function, and turn a `ValueError` into a `ModelRetry`. That last step is why
    `compute.py`'s error messages are written as instructions — they become the prompt
    the model reads next.
    """

    @agent.tool
    def percent_change(ctx: RunContext[MycelDeps], previous: float, current: float) -> float:
        """Percentage change from a previous value to a current one."""
        return _guarded(
            ctx, "percent_change", compute.percent_change, previous=previous, current=current
        )

    @agent.tool
    def absolute_change(
        ctx: RunContext[MycelDeps], previous: float, current: float
    ) -> float:
        """Plain difference between two values. Use when percent change is undefined."""
        return _guarded(
            ctx, "absolute_change", compute.absolute_change, previous=previous, current=current
        )

    @agent.tool
    def percentage(ctx: RunContext[MycelDeps], part: float, whole: float) -> float:
        """What percentage one value is of another."""
        return _guarded(ctx, "percentage", compute.percentage, part=part, whole=whole)

    @agent.tool
    def cagr(
        ctx: RunContext[MycelDeps], begin: float, end: float, periods: float
    ) -> float:
        """Compound annual growth rate, in percent, over a number of periods."""
        return _guarded(ctx, "cagr", compute.cagr, begin=begin, end=end, periods=periods)

    @agent.tool
    def share_of_total(
        ctx: RunContext[MycelDeps], values: dict[str, float]
    ) -> dict[str, float]:
        """Each named value as a percentage of their total."""
        return _guarded(ctx, "share_of_total", compute.share_of_total, values=values)

    @agent.tool
    def summary_stats(ctx: RunContext[MycelDeps], values: list[float]) -> SummaryStats:
        """Count, total, mean, median, spread and range of a series, in one call."""
        return _guarded(ctx, "summary_stats", compute.summary_stats, values=values)

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


def _guarded(
    ctx: RunContext[MycelDeps], name: str, fn: Callable[..., T], **kwargs: Any
) -> T:
    """Guard against repetition, call the function, turn refusals into re-prompts."""
    guard_repeat(ctx, name, threshold=ctx.deps.settings.repeat_threshold, **kwargs)
    try:
        return fn(**kwargs)
    except ValueError as exc:
        # compute.py writes these messages for the model to read, so pass them through
        # unchanged rather than wrapping them in our own wording.
        raise ModelRetry(str(exc)) from exc
