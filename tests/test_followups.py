"""What a follow-up carries: history for the answer, a rewritten question for the search."""

from types import SimpleNamespace
from typing import Any

import pytest

from mycel.agents.core import runner
from mycel.agents.specialists.rewriter import Rewriter
from mycel.domains import chat as domain
from mycel.infra.redis import budgets
from mycel.queue.job import Job, JobKind
from mycel.services import knowledge
from mycel.services.auth import Principal
from mycel.services.chat import (
    HISTORY_CHARS,
    HISTORY_TURNS,
    REWRITE_ANSWER_CHARS,
    _history_text,
    _rewrite_context,
)
from tests.fakes import turn as _turn

pytestmark = pytest.mark.anyio


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """`domain.run` with the model, budgets, user lookup and search replaced; records each."""
    seen: dict[str, Any] = {"rewrites": 0, "rewrite": lambda p: ""}

    async def fake_run(agent: Any, prompt: str, deps: Any) -> Any:
        if agent.name == Rewriter.name:
            seen["rewrites"] += 1
            return seen["rewrite"](prompt)
        seen["prompt"] = prompt
        raise RuntimeError("stop here")

    async def fake_retrieve(user_id: int, query: str) -> knowledge.Retrieved:
        seen["query"] = query
        return knowledge.Retrieved(version="v", query=query)

    async def noop(*a: object, **k: object) -> None:
        return None

    async def somebody(job: Job) -> Principal:
        return Principal(id=1, email="someone@example.com")

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(knowledge, "retrieve", fake_retrieve)
    monkeypatch.setattr(budgets, "load", noop)
    monkeypatch.setattr(budgets, "save", noop)
    monkeypatch.setattr(domain, "_who_asked", somebody)
    monkeypatch.setattr(domain, "find_turn", noop)
    return seen


async def _ask(**payload: Any) -> None:
    job = Job(kind=JobKind.CHAT, payload={"conversation_id": 1, "user_id": 1, **payload})
    with pytest.raises(RuntimeError, match="stop here"):
        await domain.run(job)


class TestWhatIsRemembered:
    def test_an_empty_thread_remembers_nothing(self) -> None:
        """No header, no blank block — a first question is sent as it was typed."""
        assert _history_text([]) == ""

    def test_a_finished_turn_comes_back_as_question_and_answer(self) -> None:
        text = _history_text([_turn(1, "how is MYC?", "MYC shipped four tickets.")])
        assert "Q: how is MYC?" in text
        assert "MYC shipped four tickets." in text

    def test_a_failed_turn_is_not_remembered(self) -> None:
        """A run that went wrong has nothing to recall."""
        assert _history_text([_turn(1, "how is MYC?", "", status="failed")]) == ""


class TestTheCeilings:
    def test_only_the_most_recent_turns_survive(self) -> None:
        turns = [_turn(n, f"q{n}", f"a{n}") for n in range(HISTORY_TURNS + 3)]
        text = _history_text(turns)
        assert "q0" not in text
        assert f"q{HISTORY_TURNS + 2}" in text

    def test_a_trim_says_how_much_it_dropped(self) -> None:
        """Silence would leave the model believing it can see the whole thread."""
        turns = [_turn(n, f"q{n}", f"a{n}") for n in range(HISTORY_TURNS + 2)]
        assert "2 earlier turn(s) omitted" in _history_text(turns)

    def test_one_long_answer_does_not_get_through_on_a_turn_count(self) -> None:
        """Counting turns bounds nothing: six of these would be far over the ceiling."""
        turns = [_turn(n, f"q{n}", "x" * HISTORY_CHARS) for n in range(3)]
        text = _history_text(turns)
        assert text.count("Q: ") == 1
        assert "2 earlier turn(s) omitted" in text

    def test_the_newest_turn_is_kept_even_when_it_is_over_the_ceiling(self) -> None:
        """A follow-up is about the turn just before it."""
        assert "q0" in _history_text([_turn(0, "q0", "x" * (HISTORY_CHARS * 2))])


async def test_the_history_reaches_the_prompt(worker: dict[str, Any]) -> None:
    history = "Earlier in this conversation:\n\nQ: how is MYC?\nA: Fine."
    await _ask(question="and last week?", history=history)
    assert "how is MYC?" in worker["prompt"]
    assert worker["prompt"].endswith("and last week?")


class TestContext:
    def test_a_first_question_has_none(self) -> None:
        assert _rewrite_context([]) == ""

    def test_the_last_three_questions_and_the_head_of_the_last_answer(self) -> None:
        turns = [_turn(n, f"q{n}", "x" * 900) for n in range(5)]
        text = _rewrite_context(turns)
        assert "q1" not in text and all(f"q{n}" in text for n in (2, 3, 4))
        assert "x" * REWRITE_ANSWER_CHARS in text and "x" * (REWRITE_ANSWER_CHARS + 1) not in text


KNOWLEDGE = {
    "question": "how much does it cost?",
    "chips": ["knowledge", "web"],
    "previous": "what is Qdrant?",
}
CONTEXT = "Earlier questions:\n- what is Qdrant?"
STITCHED = "what is Qdrant?\nhow much does it cost?"


class TestSearch:
    async def test_the_search_uses_the_rewrite_and_the_prompt_keeps_the_question(
        self, worker: dict[str, Any]
    ) -> None:
        worker["rewrite"] = lambda p: "Qdrant cost?"
        await _ask(**KNOWLEDGE, context=CONTEXT)
        assert worker["query"] == "Qdrant cost?"
        assert worker["prompt"].endswith("how much does it cost?")

    async def test_a_failed_rewrite_falls_back_to_stitching(self, worker: dict[str, Any]) -> None:
        def boom(prompt: str) -> str:
            raise TimeoutError("slow")

        worker["rewrite"] = boom
        await _ask(**KNOWLEDGE, context=CONTEXT)
        assert worker["query"] == STITCHED

    async def test_an_empty_rewrite_falls_back_to_stitching(self, worker: dict[str, Any]) -> None:
        worker["rewrite"] = lambda p: "  "
        await _ask(**KNOWLEDGE, context=CONTEXT)
        assert worker["query"] == STITCHED

    async def test_no_context_makes_no_call(self, worker: dict[str, Any]) -> None:
        await _ask(**KNOWLEDGE, context="")
        assert worker["rewrites"] == 0


async def test_an_answered_job_is_not_run_again(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answered(job_id: str) -> object:
        return SimpleNamespace(status="done")

    async def must_not_run(*a: object, **k: object) -> None:
        raise AssertionError("the model was called for an answered job")

    monkeypatch.setattr(domain, "find_turn", answered)
    monkeypatch.setattr(runner, "run", must_not_run)
    await domain.run(Job(kind=JobKind.CHAT, payload={"question": "q", "user_id": 1}))
