"""A follow-up's Knowledge search runs on a rewritten question; the answer sees the original."""

from typing import Any

import pytest

from mycel.agents.specialists.rewriter import Rewriter
from mycel.domains import chat as domain
from mycel.queue.job import Job, JobKind
from mycel.services import knowledge
from mycel.services.auth import Principal
from mycel.services.chat import REWRITE_ANSWER_CHARS, _rewrite_context
from tests.test_history import _turn

pytestmark = pytest.mark.anyio


class TestContext:
    def test_a_first_question_has_none(self) -> None:
        assert _rewrite_context([]) == ""

    def test_the_last_three_questions_and_the_head_of_the_last_answer(self) -> None:
        turns = [_turn(n, f"q{n}", "x" * 900) for n in range(5)]
        text = _rewrite_context(turns)
        assert "q1" not in text and all(f"q{n}" in text for n in (2, 3, 4))
        assert "x" * REWRITE_ANSWER_CHARS in text and "x" * (REWRITE_ANSWER_CHARS + 1) not in text


async def _run(monkeypatch: pytest.MonkeyPatch, context: str, rewrite: Any) -> dict[str, Any]:
    seen: dict[str, Any] = {"rewrites": 0}

    async def fake_run(agent: Any, prompt: str, deps: Any) -> Any:
        if agent.name == Rewriter.name:
            seen["rewrites"] += 1
            return rewrite(prompt)
        seen["prompt"] = prompt
        raise RuntimeError("stop here")

    async def fake_retrieve(user_id: int, query: str) -> knowledge.Retrieved:
        seen["query"] = query
        return knowledge.Retrieved(version="v", query=query)

    async def noop(*a: object, **k: object) -> None:
        return None

    async def somebody(job: Job) -> Principal:
        return Principal(id=1, email="someone@example.com")

    monkeypatch.setattr(domain.runner, "run", fake_run)
    monkeypatch.setattr(domain.knowledge, "retrieve", fake_retrieve)
    monkeypatch.setattr(domain.budgets, "load", noop)
    monkeypatch.setattr(domain.budgets, "save", noop)
    monkeypatch.setattr(domain, "_who_asked", somebody)
    monkeypatch.setattr(domain, "find_turn", noop)

    job = Job(
        kind=JobKind.CHAT,
        payload={
            "question": "how much does it cost?",
            "conversation_id": 1,
            "user_id": 1,
            "chips": ["knowledge", "web"],
            "previous": "what is Qdrant?",
            "context": context,
        },
    )
    with pytest.raises(RuntimeError, match="stop here"):
        await domain.run(job)
    return seen


class TestSearch:
    async def test_the_search_uses_the_rewrite_and_the_prompt_keeps_the_question(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = await _run(
            monkeypatch, "Earlier questions:\n- what is Qdrant?", lambda p: "Qdrant cost?"
        )
        assert seen["query"] == "Qdrant cost?"
        assert seen["prompt"].endswith("how much does it cost?")

    async def test_a_failed_rewrite_falls_back_to_stitching(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(prompt: str) -> str:
            raise TimeoutError("slow")

        seen = await _run(monkeypatch, "Earlier questions:\n- what is Qdrant?", boom)
        assert seen["query"] == "what is Qdrant?\nhow much does it cost?"

    async def test_an_empty_rewrite_falls_back_to_stitching(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = await _run(monkeypatch, "Earlier questions:\n- what is Qdrant?", lambda p: "  ")
        assert seen["query"] == "what is Qdrant?\nhow much does it cost?"

    async def test_no_context_makes_no_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = await _run(monkeypatch, "", lambda p: "unused")
        assert seen["rewrites"] == 0


async def test_an_answered_job_is_not_run_again(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    async def answered(job_id: str) -> object:
        return SimpleNamespace(status="done")

    async def must_not_run(*a: object, **k: object) -> None:
        raise AssertionError("the model was called for an answered job")

    monkeypatch.setattr(domain, "find_turn", answered)
    monkeypatch.setattr(domain.runner, "run", must_not_run)
    await domain.run(Job(kind=JobKind.CHAT, payload={"question": "q", "user_id": 1}))
