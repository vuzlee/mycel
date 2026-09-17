"""The analyst's tools: percentages, growth, basic statistics.

With a tool the model does not have to do arithmetic in its head — and arithmetic slips are
the hardest error to spot in a report, because a wrong number reads exactly like a right one.

Two halves, in one file because they are one capability:

  the functions      pure — no `RunContext`, no I/O, unit-testable without an agent
  `build_toolset()`  the same functions as a `FunctionToolset` an agent can be given

The toolset lives here rather than in the agent so a second agent needing these numbers
gets them by adding one line, not by copying wrappers.

Every `ValueError` message is written **for the model to read**: `_guarded` turns it into a
`ModelRetry`, so it has to say what to do instead, not just that something was invalid.
"""

import statistics
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.guards import guard_repeat

T = TypeVar("T")


class SummaryStats(BaseModel):
    """Descriptive statistics for one set of values."""

    n: int = Field(description="How many values were summarised.")
    total: float
    mean: float
    median: float
    stdev: float | None = Field(
        default=None,
        description="Sample standard deviation. Null when n < 2, where it is undefined.",
    )
    minimum: float
    maximum: float


def percentage(part: float, whole: float) -> float:
    """`part` as a percentage of `whole`. 25 of 200 -> 12.5."""
    if whole == 0:
        raise ValueError(
            "percentage is undefined when the whole is 0; report the raw part instead"
        )
    return part / whole * 100.0


def percent_change(previous: float, current: float) -> float:
    """Change from `previous` to `current`, in percent. 100 -> 130 is 30.0."""
    if previous == 0:
        raise ValueError(
            "percent_change is undefined when the previous value is 0; "
            "report the absolute change instead"
        )
    return (current - previous) / abs(previous) * 100.0


def absolute_change(previous: float, current: float) -> float:
    """Plain difference. The honest answer when `percent_change` is undefined."""
    return current - previous


def cagr(begin: float, end: float, periods: float) -> float:
    """Compound annual growth rate over `periods`, in percent.

    Undefined across a sign change: no real rate takes a negative value to a positive one.
    """
    if periods <= 0:
        raise ValueError("cagr needs a positive number of periods")
    if begin <= 0:
        raise ValueError(
            "cagr is undefined when the starting value is zero or negative; "
            "use percent_change over the whole span instead"
        )
    if end < 0:
        raise ValueError(
            "cagr is undefined when the ending value is negative; "
            "use absolute_change instead"
        )
    growth: float = (end / begin) ** (1.0 / periods)
    return (growth - 1.0) * 100.0


def share_of_total(values: Mapping[str, float]) -> dict[str, float]:
    """Each value as a percentage of the total. Shares sum to 100."""
    if not values:
        raise ValueError("share_of_total needs at least one value")
    total = sum(values.values())
    if total == 0:
        raise ValueError(
            "share_of_total is undefined when the values sum to 0; "
            "report the raw values instead"
        )
    return {key: value / total * 100.0 for key, value in values.items()}


def summary_stats(values: Sequence[float]) -> SummaryStats:
    """Describe a series in one call, so the model does not loop over it value by value."""
    if not values:
        raise ValueError("summary_stats needs at least one value")
    return SummaryStats(
        n=len(values),
        total=float(sum(values)),
        mean=statistics.fmean(values),
        median=statistics.median(values),
        # Undefined for a single value — null rather than a fabricated 0.0, which would
        # read as "no variance" instead of "not enough data".
        stdev=statistics.stdev(values) if len(values) > 1 else None,
        minimum=float(min(values)),
        maximum=float(max(values)),
    )


def build_toolset() -> FunctionToolset[MycelDeps]:
    """The compute functions as tools, guarded and with model-readable errors."""
    toolset: FunctionToolset[MycelDeps] = FunctionToolset()

    @toolset.tool(name="percent_change")
    def _percent_change(
        ctx: RunContext[MycelDeps], previous: float, current: float
    ) -> float:
        """Percentage change from a previous value to a current one."""
        return _guarded(
            ctx, "percent_change", percent_change, previous=previous, current=current
        )

    @toolset.tool(name="absolute_change")
    def _absolute_change(
        ctx: RunContext[MycelDeps], previous: float, current: float
    ) -> float:
        """Plain difference between two values. Use when percent change is undefined."""
        return _guarded(
            ctx, "absolute_change", absolute_change, previous=previous, current=current
        )

    @toolset.tool(name="percentage")
    def _percentage(
        ctx: RunContext[MycelDeps], part: float, whole: float
    ) -> float:
        """What percentage one value is of another."""
        return _guarded(ctx, "percentage", percentage, part=part, whole=whole)

    @toolset.tool(name="cagr")
    def _cagr(
        ctx: RunContext[MycelDeps], begin: float, end: float, periods: float
    ) -> float:
        """Compound annual growth rate, in percent, over a number of periods."""
        return _guarded(ctx, "cagr", cagr, begin=begin, end=end, periods=periods)

    @toolset.tool(name="share_of_total")
    def _share_of_total(
        ctx: RunContext[MycelDeps], values: dict[str, float]
    ) -> dict[str, float]:
        """Each named value as a percentage of their total."""
        return _guarded(ctx, "share_of_total", share_of_total, values=values)

    @toolset.tool(name="summary_stats")
    def _summary_stats(
        ctx: RunContext[MycelDeps], values: list[float]
    ) -> SummaryStats:
        """Count, total, mean, median, spread and range of a series, in one call."""
        return _guarded(ctx, "summary_stats", summary_stats, values=values)

    return toolset


def _guarded(
    ctx: RunContext[MycelDeps], name: str, fn: Callable[..., T], **kwargs: Any
) -> T:
    """Guard against repetition, call the function, turn refusals into re-prompts."""
    guard_repeat(ctx, name, threshold=ctx.deps.settings.repeat_threshold, **kwargs)
    try:
        return fn(**kwargs)
    except ValueError as exc:
        raise ModelRetry(str(exc)) from exc
