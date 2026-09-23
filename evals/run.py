"""Run the golden set and report what it scored.

    uv run python -m evals.run                     run every case, print the table
    uv run python -m evals.run --compare-baseline  also fail if the score dropped
    uv run python -m evals.run --save-baseline     record this run as the new baseline

Costs money: every case is a real model call. That is the point — an eval that mocks the
model measures the mock. CI only runs this when a pull request touches prompts or `llm/`.

A run with an empty golden set exits 0 and says so. A CI step that fails because nobody
has written the cases yet teaches people to ignore the step.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from evals.case import Case, Check, load_all
from mycel.agents.core.runner import run
from mycel.agents.registry import build, build_deps
from mycel.agents.schemas import ProgressSummary

GOLDEN = Path(__file__).parent / "golden"
BASELINE = Path(__file__).parent / "baseline.json"

#: What one eval run may spend in total. Small on purpose: a runaway here is a bill, not a
#: failed test, and a golden set large enough to exceed this wants its own decision.
CEILING_USD = "1.00"


@dataclass(frozen=True)
class Result:
    """One case, scored."""

    case: str
    checks: list[Check]
    error: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for check in self.checks if check.passed)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def score(self) -> float:
        """Fraction of checks that held. A case that errored scores zero, not nothing."""
        return self.passed / self.total if self.total else 0.0


async def run_case(case: Case) -> Result:
    """One case against the real summariser. An error is a zero, never a crash."""
    try:
        summary = await run(
            build("summariser"),
            case.prompt,
            build_deps(job_id=f"eval:{case.name}", ceiling_usd=CEILING_USD),
        )
    except Exception as exc:
        return Result(case.name, [], error=f"{type(exc).__name__}: {exc}")
    assert isinstance(summary, ProgressSummary)
    return Result(case.name, case.check(summary))


async def run_all(cases: list[Case]) -> list[Result]:
    """Every case, one after another.

    Sequential rather than gathered: the free tier is 20 requests a day, and a burst that
    trips a rate limit reports as a quality failure when it is a scheduling one.
    """
    return [await run_case(case) for case in cases]


def report(results: list[Result]) -> float:
    """Print the table and return the overall score."""
    for result in results:
        if result.error:
            print(f"  ERROR  {result.case:<28} {result.error}")
            continue
        mark = "ok" if result.passed == result.total else "FAIL"
        print(f"  {mark:<6} {result.case:<28} {result.passed}/{result.total}")
        for check in result.checks:
            if not check.passed:
                detail = f" — {check.detail}" if check.detail else ""
                print(f"         · {check.name}{detail}")

    overall = sum(r.score for r in results) / len(results) if results else 0.0
    print(f"\n  score {overall:.3f} over {len(results)} case(s)")
    return overall


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compare-baseline",
        action="store_true",
        help="fail when this run scores below the recorded baseline",
    )
    parser.add_argument(
        "--save-baseline", action="store_true", help="record this run's score as the baseline"
    )
    args = parser.parse_args(argv)

    cases = load_all(GOLDEN)
    if not cases:
        print(f"No cases in {GOLDEN}/ — nothing to score.")
        return 0

    overall = report(asyncio.run(run_all(cases)))

    if args.save_baseline:
        BASELINE.write_text(json.dumps({"score": round(overall, 4)}, indent=2) + "\n")
        print(f"  baseline saved: {overall:.3f}")

    if args.compare_baseline:
        if not BASELINE.exists():
            print("  no baseline recorded yet — nothing to compare against")
            return 0
        previous = float(json.loads(BASELINE.read_text())["score"])
        print(f"  baseline {previous:.3f}")
        if overall < previous:
            print("  SCORE DROPPED — this change makes the summary worse")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
