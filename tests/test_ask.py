"""The ask domain: gates before Gemini, one call, citations checked, quota given back.

Search, Postgres, Redis and the model are replaced at the module boundary, so this runs
with nothing up. `test_ask_quota.py` covers the quota against a real Redis.
"""

from dataclasses import dataclass
from typing import Any

import pytest

from mycel.agents.schemas import Citation, NotebookAnswer
from mycel.domains import ask
from mycel.infra.postgres.repositories.notebooks import ChunkRow
from mycel.infra.vectors.documents import Hit
from mycel.queue.job import Job, JobKind
from mycel.services.notebooks import NotebookError

pytestmark = pytest.mark.anyio


def chunk(i: int, text: str) -> ChunkRow:
    return ChunkRow(i, 10, 1, "bert.pdf", "application/pdf", i, text, "Intro", 3)


@dataclass
class World:
    hits: list[Hit]
    chunks: list[ChunkRow]
    model: NotebookAnswer | Exception
    reserved: bool = True
    calls: int = 0
    released: int = 0
    finished: dict[str, Any] | None = None
    cached: dict[str, Any] | None = None


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    w = World(
        hits=[Hit(1, 10, 0.9), Hit(2, 10, 0.85)],
        chunks=[chunk(1, "BERT masks 15% of tokens."), chunk(2, "It uses NSP.")],
        model=NotebookAnswer(
            answer="It masks 15% [c1].",
            citations=[Citation(id="c1", quote="masks 15% of tokens")],
            answered=True,
        ),
    )

    async def search(notebook_id: int, query: str, limit: int) -> list[Hit]:
        return w.hits

    class Repo:
        def __init__(self, session: object) -> None: ...

        async def readable_chunks(self, ids: list[int], owner_id: int) -> list[ChunkRow]:
            return [c for c in w.chunks if c.id in ids]

    class Scope:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *exc: object) -> None:
            return None

    async def reserve(user_id: int, per_user: int, system: int) -> bool:
        return w.reserved

    async def release(user_id: int) -> None:
        w.released += 1

    async def model(job: Job, owner: int, question: str, labelled: dict[str, Any]) -> Any:
        w.calls += 1
        if isinstance(w.model, Exception):
            raise w.model
        return w.model

    async def finish(
        job: Job, nb: int, v: str, q: str, text: str, sources: list[Any], *, cache: bool
    ) -> None:
        w.finished = {"text": text, "sources": sources, "cache": cache}

    monkeypatch.setattr(ask.vectors, "search", search)
    monkeypatch.setattr(ask, "NotebookRepository", Repo)
    monkeypatch.setattr(ask, "session_scope", lambda: Scope())
    monkeypatch.setattr(ask.quota, "reserve", reserve)
    monkeypatch.setattr(ask.quota, "release", release)
    monkeypatch.setattr(ask, "_ask_model", model)
    monkeypatch.setattr(ask, "_finish", finish)
    return w


def job() -> Job:
    return Job(
        kind=JobKind.ASK,
        payload={"notebook_id": 1, "question": "masking?", "user_id": 7, "version": "v"},
    )


class TestRun:
    async def test_a_grounded_answer_keeps_its_citation(self, world: World) -> None:
        await ask.run(job())

        assert world.calls == 1
        assert world.finished is not None
        assert world.finished["text"] == "It masks 15% [c1]."
        assert [s["chunk_id"] for s in world.finished["sources"]] == [1]

    async def test_below_the_threshold_gemini_is_not_called(self, world: World) -> None:
        world.hits = [Hit(1, 10, 0.70)]

        await ask.run(job())

        assert world.calls == 0
        assert world.finished is not None
        assert world.finished["text"] == ask.NOT_FOUND

    async def test_passages_dropped_by_layer_two_are_not_sent(self, world: World) -> None:
        world.chunks = []

        await ask.run(job())

        assert world.calls == 0
        assert world.finished is not None
        assert world.finished["text"] == ask.NOT_FOUND

    async def test_an_answer_whose_citations_all_fail_is_refused(self, world: World) -> None:
        world.model = NotebookAnswer(
            answer="Half of them [c9].", citations=[Citation(id="c9", quote="x")], answered=True
        )

        await ask.run(job())

        assert world.finished is not None
        assert world.finished["text"] == ask.NOT_GROUNDED
        assert world.finished["sources"] == []

    async def test_not_answered_is_passed_through_without_sources(self, world: World) -> None:
        world.model = NotebookAnswer(
            answer="The documents in this notebook do not cover that.", answered=False
        )

        await ask.run(job())

        assert world.finished is not None
        assert world.finished["text"].startswith("The documents")
        assert world.finished["sources"] == []

    async def test_a_failed_call_gives_the_question_back(self, world: World) -> None:
        world.model = OSError("provider down")

        with pytest.raises(OSError):
            await ask.run(job())

        assert world.released == 1

    async def test_out_of_quota_at_run_time_calls_nothing(self, world: World) -> None:
        world.reserved = False

        await ask.run(job())

        assert world.calls == 0
        assert world.finished is not None
        assert world.finished["text"] == ask.OUT_OF_QUOTA
        assert world.finished["cache"] is False


class TestRender:
    def test_passages_are_labelled_with_their_source(self) -> None:
        text = ask.render("q?", {"c1": chunk(1, "body")})

        assert "[c1] (bert.pdf, page 3, Intro)\nbody" in text
        assert text.endswith("Question: q?")


class TestRequestGates:
    async def test_an_empty_question_is_refused(self) -> None:
        with pytest.raises(NotebookError) as caught:
            await ask.request_ask(1, 1, "   ")
        assert caught.value.status == 422

    async def test_a_long_question_is_refused(self) -> None:
        with pytest.raises(NotebookError) as caught:
            await ask.request_ask(1, 1, "x" * 501)
        assert caught.value.status == 422
