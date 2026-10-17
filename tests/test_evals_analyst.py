"""The analyst golden set parses and the scoring says what it means."""

from pathlib import Path

from evals.analyst.case import Case, Run, load_all
from mycel.agents.specialists.analyst import Analysis, Figure

GOLDEN = Path(__file__).parent.parent / "evals" / "analyst" / "golden"


def _run(tools: list[str], requests: int = 2, source: str = "hours_by_person") -> Run:
    figure = Figure(label="hours", value=85.5, unit="h", source=source)
    return Run(Analysis(figures=[figure], findings=["x"]), tools, requests)


def _failed(case: Case, run: Run) -> set[str]:
    return {check.name for check in case.check(run) if not check.passed}


CASE = Case("c", "q", tools=["hours_by_person"], never=["run_sql"], max_requests=3)


class TestGoldenSet:
    def test_every_case_parses(self) -> None:
        cases = load_all(GOLDEN)
        assert len(cases) == 5
        assert all(case.question.strip() and case.tools for case in cases)


class TestScoring:
    def test_a_ready_read_and_stop_passes(self) -> None:
        assert not _failed(CASE, _run(["hours_by_person", "final_result"]))

    def test_rechecking_with_sql_fails(self) -> None:
        assert _failed(CASE, _run(["hours_by_person", "run_sql"])) == {"skipped run_sql"}

    def test_too_many_rounds_fail(self) -> None:
        assert _failed(CASE, _run(["hours_by_person"], requests=6)) == {"requests <= 3"}

    def test_an_uncited_figure_fails(self) -> None:
        assert "every figure cited" in _failed(CASE, _run(["hours_by_person"], source=" "))
