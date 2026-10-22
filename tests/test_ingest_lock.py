"""Ingest embeds with no transaction open; the row lock covers only the writes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mycel.domains import ingest
from mycel.infra.objects import files
from mycel.infra.postgres.document_status import DELETING, READY
from mycel.infra.redis import document_events
from mycel.infra.vectors import documents as vectors
from mycel.queue.job import Job, JobKind

pytestmark = pytest.mark.anyio


class World:
    """One document, its row status, and what happened to it, in order."""

    def __init__(self, status_at_lock: str = "parsing") -> None:
        self.open_sessions = 0
        self.status_at_lock = status_at_lock
        self.events: list[str] = []


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    w = World()

    @asynccontextmanager
    async def scope() -> AsyncIterator[None]:
        w.open_sessions += 1
        try:
            yield None
        finally:
            w.open_sessions -= 1

    class Repo:
        def __init__(self, session: object) -> None: ...

        async def document(self, document_id: int) -> Any:
            return SimpleNamespace(
                status="queued", user_id=1, filename="a.pdf", object_key="k", enabled=True
            )

        async def start_parsing(self, document_id: int) -> None: ...

        async def lock_document(self, document_id: int) -> Any:
            w.events.append("lock")
            return SimpleNamespace(status=w.status_at_lock, user_id=1, enabled=True)

        async def replace_chunks(self, document_id: int, chunks: list[Any]) -> list[int]:
            w.events.append("chunks")
            return list(range(len(chunks)))

        async def set_status(self, document_id: int, status: str, **_: Any) -> None:
            w.events.append(status)

    async def embed(texts: list[str]) -> list[list[float]]:
        w.events.append(f"embed with {w.open_sessions} open")
        return [[0.0] for _ in texts]

    async def write(*args: Any) -> None:
        w.events.append("write")

    async def delete(document_id: int) -> None: ...

    async def nothing(*args: Any, **kwargs: Any) -> None: ...

    async def parsed(path: Path) -> Any:
        return 1, [SimpleNamespace(text="t", section_path="", page_start=1, page_end=1, tokens=1)]

    monkeypatch.setattr(ingest, "session_scope", scope)
    monkeypatch.setattr(ingest, "DocumentRepository", Repo)
    monkeypatch.setattr(vectors, "embed_passages", embed)
    monkeypatch.setattr(vectors, "write", write)
    monkeypatch.setattr(vectors, "delete", delete)
    monkeypatch.setattr(files, "download", nothing)
    monkeypatch.setattr(document_events, "changed", nothing)
    monkeypatch.setattr(ingest, "_parse_and_chunk", parsed)
    return w


async def test_the_embedding_runs_before_the_lock_with_no_session_open(world: World) -> None:
    await ingest.run(Job(kind=JobKind.INGEST, payload={"document_id": 1}))
    assert world.events == ["embed with 0 open", "lock", "chunks", "write", READY]


async def test_a_document_deleted_while_embedding_is_not_written(world: World) -> None:
    world.status_at_lock = DELETING
    await ingest.run(Job(kind=JobKind.INGEST, payload={"document_id": 1}))
    assert world.events == ["embed with 0 open", "lock"]
