"""What a follow-up carries from the turns before it.

The trimming is Mycel's, not the framework's — the history goes into the prompt as text
rather than as `message_history` — so the caps and the "omitted" line are behaviour worth
pinning down here. No database and no model: `_recall` takes rows and returns a string,
which is the shape that makes it testable at all.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from mycel.domains.report import (
    HISTORY_CHARS,
    HISTORY_TURNS,
    _recall,
    _run_report,
    _said,
)
from mycel.infra.postgres.repositories.app import ReportRow
from mycel.queue.job import Job, JobKind

pytestmark = pytest.mark.anyio


def _turn(n: int, question: str, findings: list[str], status: str = "done") -> ReportRow:
    body: dict[str, Any] | None = {
        "findings": [{"statement": text, "sources": []} for text in findings],
        "gaps": [],
    }
    return ReportRow(
        id=n,
        conversation_id=1,
        job_id=f"job-{n}",
        question=question,
        status=status,
        body=body if status == "done" else None,
        error=None,
        spent_usd=Decimal("0.01"),
        created_at=datetime.now(UTC) + timedelta(seconds=n),
    )


class TestWhatIsRemembered:
    def test_an_empty_thread_remembers_nothing(self) -> None:
        """No header, no blank block — a first question is sent as it was typed."""
        assert _recall([]) == ""

    def test_a_finished_turn_comes_back_as_question_and_answer(self) -> None:
        text = _recall([_turn(1, "how is MYC?", ["MYC shipped four tickets."])])
        assert "Q: how is MYC?" in text
        assert "MYC shipped four tickets." in text

    def test_a_failed_turn_is_not_remembered(self) -> None:
        """A run that went wrong has nothing to recall, and showing a model how a run
        failed is an example to follow rather than context."""
        assert _recall([_turn(1, "how is MYC?", [], status="failed")]) == ""


class TestTheCeilings:
    def test_only_the_most_recent_turns_survive(self) -> None:
        turns = [_turn(n, f"q{n}", [f"a{n}"]) for n in range(HISTORY_TURNS + 3)]
        text = _recall(turns)
        assert "q0" not in text
        assert f"q{HISTORY_TURNS + 2}" in text

    def test_a_trim_says_how_much_it_dropped(self) -> None:
        """Silence would leave the model believing it can see the whole thread."""
        turns = [_turn(n, f"q{n}", [f"a{n}"]) for n in range(HISTORY_TURNS + 2)]
        assert "2 earlier turn(s) omitted" in _recall(turns)

    def test_one_long_answer_does_not_get_through_on_a_turn_count(self) -> None:
        """Counting turns bounds nothing: six of these would be far over the ceiling."""
        turns = [_turn(n, f"q{n}", ["x" * HISTORY_CHARS]) for n in range(3)]
        text = _recall(turns)
        assert text.count("Q: ") == 1
        assert "2 earlier turn(s) omitted" in text

    def test_the_newest_turn_is_kept_even_when_it_is_over_the_ceiling(self) -> None:
        """A follow-up is about the turn just before it. Dropping that one to respect a
        character count would leave the history that matters least."""
        assert "q0" in _recall([_turn(0, "q0", ["x" * (HISTORY_CHARS * 2)])])


class TestFlattening:
    def test_sources_and_follow_ups_are_left_out(self) -> None:
        """A url the model cannot open and a question nobody asked are both noise, and a
        follow-up would come back as a question the model believes it was given."""
        said = _said(
            {
                "findings": [{"statement": "Four tickets shipped.", "sources": ["MYC-1"]}],
                "gaps": [],
                "follow_ups": ["Who shipped them?"],
            }
        )
        assert said == "Four tickets shipped."

    def test_a_gap_is_recalled_as_a_gap(self) -> None:
        assert _said({"findings": [], "gaps": ["No mail access."]}) == "Unanswered: No mail access."

    def test_an_empty_answer_still_says_something(self) -> None:
        assert _said({"findings": [], "gaps": []}) == "(no findings)"


class TestTheWorkerUsesIt:
    async def test_the_history_reaches_the_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The payload carries it, so the worker never re-reads it from the database —
        see `enqueue_report` for why the idempotency key makes that mandatory."""
        seen: list[str] = []

        async def fake_run(agent: object, prompt: str, deps: Any) -> Any:
            seen.append(prompt)
            raise RuntimeError("stop here")

        from mycel.domains import report as domain

        monkeypatch.setattr(domain.runner, "run", fake_run)
        monkeypatch.setattr(domain.budgets, "load", lambda *a, **k: _noop())
        monkeypatch.setattr(domain.budgets, "save", lambda *a, **k: _noop())

        job = Job(
            kind=JobKind.REPORT,
            payload={
                "question": "and last week?",
                "conversation_id": 1,
                "history": "Earlier in this conversation:\n\nQ: how is MYC?\nA: Fine.",
            },
        )
        try:
            await _run_report(job)
        except RuntimeError:
            pass

        assert "how is MYC?" in seen[0]
        assert seen[0].endswith("and last week?")


async def _noop() -> Any:
    return None
