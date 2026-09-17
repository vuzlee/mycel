"""Computation tool: percentages, growth, basic statistics.

With a tool the model does not have to do arithmetic in its head — and arithmetic slips are
the hardest error to spot in a report, because a wrong number reads exactly like a right one.

Pure functions: no `RunContext`, no pydantic-ai import, no I/O. They are unit-testable on
their own, and `analyst.py` is what wraps them as tools.

Every `ValueError` message here is written **for the model to read**. When a tool fails,
`analyst.py` turns the message into a `ModelRetry`, so it has to say what to do instead —
not just that something was invalid.
"""

import statistics
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field


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
