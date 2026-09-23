"""The golden set parses and the scoring says what it means.

No model is called here — that is `evals/run.py`'s job and it costs money. What this
guards is the half that can break silently: a case file with a typo'd key scores every run
against a check nobody wrote, and a scorer that is wrong makes every eval result a lie.
"""

from pathlib import Path

import pytest
from evals.case import HEADLINE_MAX, Case, load_all

from mycel.agents.schemas import LoadLine, ProgressSummary, WorkLine

GOLDEN = Path(__file__).parent.parent / "evals" / "golden"


def _summary(**kwargs: object) -> ProgressSummary:
    defaults: dict[str, object] = {"period": "14-20 September 2026", "headline": "A week."}
    return ProgressSummary(**{**defaults, **kwargs})  # type: ignore[arg-type]


def _failed(case: Case, summary: ProgressSummary) -> set[str]:
    return {check.name for check in case.check(summary) if not check.passed}


class TestGoldenSet:
    def test_every_case_parses(self) -> None:
        cases = load_all(GOLDEN)
        assert cases, "the golden set is empty — evals would score nothing"
        assert all(case.prompt.strip() for case in cases)

    def test_case_names_are_unique(self) -> None:
        names = [case.name for case in load_all(GOLDEN)]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("case", load_all(GOLDEN), ids=lambda c: c.name)
    def test_expectations_are_self_consistent(self, case: Case) -> None:
        """A key cannot be required present and absent at once."""
        required = set(case.at_risk_keys) | set(case.shipped_keys)
        assert not required & set(case.absent_keys)

    @pytest.mark.parametrize("case", load_all(GOLDEN), ids=lambda c: c.name)
    def test_expected_keys_appear_in_the_prompt(self, case: Case) -> None:
        """Expecting a key the prompt never mentions asks the model to invent it."""
        for key in set(case.at_risk_keys) | set(case.shipped_keys):
            assert key in case.prompt


class TestScoring:
    def test_a_correct_answer_passes_everything(self) -> None:
        case = Case(
            name="x",
            prompt="",
            health="at_risk",
            at_risk_keys=["MYC-32"],
            shipped_keys=["MYC-31"],
            load_people=["vu le"],
            notes_contain=["dropped"],
        )
        summary = _summary(
            health="at_risk",
            shipped=[WorkLine(key="MYC-31", title="Done")],
            at_risk=[WorkLine(key="MYC-32", title="Late")],
            load=[LoadLine(person="Vu Le")],
            notes=["140 older items were dropped"],
        )
        assert _failed(case, summary) == set()

    def test_the_wrong_verdict_fails(self) -> None:
        case = Case(name="x", prompt="", health="at_risk")
        assert "health" in _failed(case, _summary(health="on_track"))

    def test_a_late_item_filed_as_in_flight_fails(self) -> None:
        case = Case(name="x", prompt="", at_risk_keys=["MYC-32"])
        summary = _summary(in_flight=[WorkLine(key="MYC-32", title="Late")])
        assert "at_risk has MYC-32" in _failed(case, summary)

    def test_an_invented_key_fails_wherever_it_is_put(self) -> None:
        case = Case(name="x", prompt="", absent_keys=["MYC-99"])
        for field in ("shipped", "in_flight", "at_risk"):
            summary = _summary(**{field: [WorkLine(key="MYC-99", title="Made up")]})
            assert "invented MYC-99" in _failed(case, summary)

    def test_a_missing_headline_fails(self) -> None:
        assert "headline is one sentence" in _failed(Case("x", ""), _summary(headline=""))

    def test_a_paragraph_headline_fails(self) -> None:
        long = "x" * (HEADLINE_MAX + 1)
        assert "headline is one sentence" in _failed(Case("x", ""), _summary(headline=long))

    def test_people_match_regardless_of_case(self) -> None:
        case = Case(name="x", prompt="", load_people=["VU LE"])
        assert _failed(case, _summary(load=[LoadLine(person="vu le")])) == set()

    def test_extra_at_risk_rows_are_allowed(self) -> None:
        """Judging more things risky is a defensible call; missing a late one is not."""
        case = Case(name="x", prompt="", at_risk_keys=["MYC-32"])
        summary = _summary(
            at_risk=[WorkLine(key="MYC-32", title="Late"), WorkLine(key="MYC-41", title="Also")]
        )
        assert _failed(case, summary) == set()
