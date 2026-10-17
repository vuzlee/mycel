"""One analyst question over gold, and how its run is scored: tools, rounds, citations."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from evals.summarizer.case import Check
from mycel.agents.specialists.analyst import Analysis


@dataclass(frozen=True)
class Run:
    """What one run did: the answer, the tools in call order, and the model requests."""

    analysis: Analysis
    tools: list[str]
    requests: int


@dataclass(frozen=True)
class Case:
    name: str
    question: str
    #: Tools the run must call.
    tools: list[str] = field(default_factory=list)
    #: Tools the run must not call: a ready read makes `run_sql` a detour.
    never: list[str] = field(default_factory=list)
    #: Model requests at most, the round trips this question is worth.
    max_requests: int = 4
    #: At least this many figures, each with a source.
    min_figures: int = 1

    def check(self, run: Run) -> list[Check]:
        checks = [Check(f"called {tool}", tool in run.tools) for tool in self.tools]
        checks += [Check(f"skipped {tool}", tool not in run.tools) for tool in self.never]
        checks.append(
            Check(
                f"requests <= {self.max_requests}",
                run.requests <= self.max_requests,
                f"got {run.requests}",
            )
        )
        figures = run.analysis.figures
        checks.append(
            Check(
                f"figures >= {self.min_figures}",
                len(figures) >= self.min_figures,
                f"got {len(figures)}",
            )
        )
        uncited = [f.label for f in figures if not f.source.strip()]
        checks.append(Check("every figure cited", not uncited, ", ".join(uncited)))
        return checks


def load_all(directory: Path) -> list[Case]:
    return [_case(path) for path in sorted(directory.glob("*.yaml"))]


def _case(path: Path) -> Case:
    raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    expect: dict[str, Any] = raw.get("expect") or {}
    return Case(
        name=path.stem,
        question=raw["question"],
        tools=list(expect.get("tools") or []),
        never=list(expect.get("never") or []),
        max_requests=int(expect.get("max_requests", 4)),
        min_figures=int(expect.get("min_figures", 1)),
    )
