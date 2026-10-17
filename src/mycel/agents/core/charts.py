"""Charts in an answer: one small shape, drawn from a tool's rows or checked against them.

A tool builds its chart from the rows it read, so the numbers cannot drift. A model may
write a ```chart block too; it is kept only when every value it plots was returned by a
tool this turn, and dropped when a tool already drew one.
"""

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

#: Past this a bar chart is a wall; the table under it says the rest.
MAX_POINTS = 24

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_BLOCK = re.compile(r"\n?```chart\s*\n(.*?)\n```\n?", re.S)


class Chart(BaseModel):
    type: Literal["bar", "line"]
    title: str = Field(max_length=120)
    unit: str = Field(default="", max_length=16)
    labels: list[str] = Field(min_length=2, max_length=MAX_POINTS)
    values: list[float] = Field(min_length=2, max_length=MAX_POINTS)


def build(
    kind: Literal["bar", "line"], title: str, unit: str, points: list[tuple[str, float]]
) -> dict[str, Any] | None:
    """A chart from (label, value) pairs; `None` when there is too little to draw."""
    points = points[:MAX_POINTS]
    if len(points) < 2:
        return None
    return Chart(
        type=kind,
        title=title,
        unit=unit,
        labels=[label[:40] for label, _ in points],
        values=[round(value, 2) for _, value in points],
    ).model_dump()


def numbers(text: str) -> set[float]:
    """Every number in a tool's result, as the model would have read it."""
    return {round(float(n), 2) for n in _NUMBER.findall(text)}


def settle(answer: str, seen: set[float], drawn: bool) -> str:
    """The answer with each model-written chart kept only if it plots what tools returned."""

    def check(match: re.Match[str]) -> str:
        if drawn:
            return "\n"
        try:
            chart = Chart.model_validate(json.loads(match.group(1)))
        except (ValueError, ValidationError):
            return "\n"
        if len(chart.labels) != len(chart.values):
            return "\n"
        if not all(_known(v, seen) for v in chart.values):
            return "\n"
        return f"\n```chart\n{chart.model_dump_json()}\n```\n"

    return _BLOCK.sub(check, answer).strip()


def _known(value: float, seen: set[float]) -> bool:
    """Returned by a tool, allowing for rounding to a whole number or one decimal."""
    v = round(value, 2)
    return any(abs(v - s) <= max(0.051, abs(s) * 0.005) for s in seen)
