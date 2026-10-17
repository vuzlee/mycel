"""`chat.run` as four steps: a Knowledge turn the documents settle never reaches a model."""

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from mycel.agents.core import runner
from mycel.core.principal import Principal
from mycel.domains import chat
from mycel.infra.redis import answers, budgets, citations
from mycel.queue.job import Job, JobKind
from mycel.services import knowledge

pytestmark = pytest.mark.anyio


async def _drop(event: Any) -> None:
    pass


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {"model": 0, "finished": [], "cached": [], "usage": []}

    async def nothing(*_: Any, **__: Any) -> None: ...

    async def no_turn(job_id: str) -> None: ...

    async def asker(job: Job) -> Principal:
        return Principal(id=7, email="a@example.com")

    async def deps(*_: Any) -> Any:
        budget = SimpleNamespace(spent_usd=Decimal("0"), tokens_in=700, tokens_out=200)
        return SimpleNamespace(budget=budget, model=None)

    async def query(*_: Any) -> str:
        return "q"

    async def model(*_: Any) -> str:
        seen["model"] += 1
        return "from the model [1]"

    async def finish(job: Job, answer: str, *rest: Any) -> None:
        seen["finished"].append(answer)
        seen["usage"].append(rest[-1])

    async def no_cache(*_: Any) -> None:
        return None

    async def put(*args: Any) -> None:
        seen["cached"].append(args[-1]["answer"])

    monkeypatch.setattr(chat, "find_turn", no_turn)
    monkeypatch.setattr(chat, "_who_asked", asker)
    monkeypatch.setattr(chat, "_deps", deps)
    monkeypatch.setattr(chat, "RedisEventChannel", lambda job_id: SimpleNamespace())
    monkeypatch.setattr(
        chat, "RecordingChannel", lambda inner: SimpleNamespace(dropped=0, steps=[], publish=_drop)
    )
    monkeypatch.setattr(chat, "search_query", query)
    monkeypatch.setattr(chat, "_finish", finish)
    monkeypatch.setattr(budgets, "save", nothing)
    monkeypatch.setattr(citations, "store", nothing)
    monkeypatch.setattr(answers, "get", no_cache)
    monkeypatch.setattr(answers, "put", put)
    monkeypatch.setattr(runner, "run", model)
    monkeypatch.setattr(chat, "cite", lambda job, a, f: (a, []))
    seen["retrieve"] = lambda found: monkeypatch.setattr(knowledge, "retrieve", _returns(found))
    return seen


def _returns(value: Any) -> Any:
    async def f(*_: Any) -> Any:
        return value

    return f


def _job(chips: list[str]) -> Job:
    return Job(kind=JobKind.CHAT, payload={"question": "what?", "user_id": 7, "chips": chips})


async def test_no_passages_is_answered_without_a_model(world: dict[str, Any]) -> None:
    world["retrieve"](knowledge.Retrieved(version="v", query="q"))
    await chat.run(_job(["knowledge"]))
    assert world["model"] == 0
    assert world["finished"] == [knowledge.NOT_FOUND]


async def test_passages_go_to_the_model_and_the_answer_is_cached(world: dict[str, Any]) -> None:
    passage: Any = SimpleNamespace(filename="a.pdf", page_start=1, section_path="", text="t")
    world["retrieve"](knowledge.Retrieved(version="v", query="q", labelled={"1": passage}))
    await chat.run(_job(["knowledge"]))
    assert world["model"] == 1
    assert world["finished"] == world["cached"] == ["from the model [1]"]


async def test_without_knowledge_nothing_is_retrieved(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def never(*_: Any) -> None:
        raise AssertionError("retrieved without the Knowledge chip")

    monkeypatch.setattr(knowledge, "retrieve", never)
    await chat.run(_job(["web"]))
    assert world["model"] == 1
    assert world["cached"] == []


async def test_an_answer_records_what_it_used(world: dict[str, Any]) -> None:
    """Model, tokens and run time reach the turn with the answer."""
    await chat.run(_job(["web"]))
    usage = world["usage"][0]
    assert (usage.model_ref, usage.tokens_in, usage.tokens_out) == (
        "host:claude-sonnet-5",
        700,
        200,
    )
    assert usage.duration_ms >= 0
