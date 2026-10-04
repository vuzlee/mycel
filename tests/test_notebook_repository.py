"""Notebook SQL against a real Postgres: ownership, busy, chunk reads, the watchdog."""

import os
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mycel.infra.postgres import notebooks as tables
from mycel.infra.postgres.engine import async_dsn
from mycel.infra.postgres.models import Base
from mycel.infra.postgres.repositories.app import AppRepository
from mycel.infra.postgres.repositories.notebooks import NewChunk, NotebookRepository

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="no test database"),
]

DSN = os.environ.get("DATABASE_URL", "")
assert not DSN or DSN.rsplit("/", 1)[-1].endswith("_test"), f"refusing to run against {DSN}"
SCHEMAS = ("bronze", "silver", "gold", "app")


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_dsn(DSN))
    async with engine.begin() as conn:
        for schema in SCHEMAS:
            await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            yield db
    finally:
        async with engine.begin() as conn:
            for schema in SCHEMAS:
                await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await engine.dispose()


async def _owner(session: AsyncSession, email: str) -> int:
    return (await AppRepository(session).create_user(email, "x")).id


async def _ready_doc(repo: NotebookRepository, notebook_id: int, sha: str) -> int:
    doc = await repo.add_document(notebook_id, f"{sha}.pdf", "application/pdf", 10, sha)
    await repo.replace_chunks(doc.id, [NewChunk(0, "text", "", 1, 1, 1)])
    await repo.set_status(doc.id, tables.READY)
    return doc.id


class TestOwnership:
    async def test_someone_elses_notebook_is_not_found(self, session: AsyncSession) -> None:
        repo = NotebookRepository(session)
        a, b = await _owner(session, "a@x.com"), await _owner(session, "b@x.com")
        nb = await repo.create_notebook(a, "mine")

        assert await repo.notebook(nb.id, a) is not None
        assert await repo.notebook(nb.id, b) is None

    async def test_someone_elses_chunk_is_not_readable(self, session: AsyncSession) -> None:
        repo = NotebookRepository(session)
        a, b = await _owner(session, "a@x.com"), await _owner(session, "b@x.com")
        nb = await repo.create_notebook(a, "mine")
        doc_id = await _ready_doc(repo, nb.id, "s1")
        ids = await repo.replace_chunks(doc_id, [NewChunk(0, "hello", "", 1, 1, 1)])

        assert [c.text for c in await repo.readable_chunks(ids, a)] == ["hello"]
        assert await repo.readable_chunks(ids, b) == []


class TestLayerTwo:
    async def test_a_disabled_document_has_no_readable_chunks(self, session: AsyncSession) -> None:
        repo = NotebookRepository(session)
        a = await _owner(session, "a@x.com")
        nb = await repo.create_notebook(a, "n")
        doc_id = await _ready_doc(repo, nb.id, "s1")
        ids = await repo.replace_chunks(doc_id, [NewChunk(0, "t", "", 1, 1, 1)])

        await repo.set_enabled(doc_id, False)

        assert await repo.readable_chunks(ids, a) == []

    async def test_a_deleting_document_has_no_readable_chunks(self, session: AsyncSession) -> None:
        repo = NotebookRepository(session)
        a = await _owner(session, "a@x.com")
        nb = await repo.create_notebook(a, "n")
        doc_id = await _ready_doc(repo, nb.id, "s1")
        ids = await repo.replace_chunks(doc_id, [NewChunk(0, "t", "", 1, 1, 1)])

        await repo.set_status(doc_id, tables.DELETING)

        assert await repo.readable_chunks(ids, a) == []


class TestBusy:
    async def test_busy_while_a_document_is_in_flight(self, session: AsyncSession) -> None:
        repo = NotebookRepository(session)
        a = await _owner(session, "a@x.com")
        nb = await repo.create_notebook(a, "n")
        other = await repo.create_notebook(a, "other")
        await repo.add_document(nb.id, "f.pdf", "application/pdf", 1, "s1")

        assert await repo.busy(nb.id) is True
        assert await repo.busy(other.id) is False

    async def test_a_failed_document_does_not_lock(self, session: AsyncSession) -> None:
        repo = NotebookRepository(session)
        a = await _owner(session, "a@x.com")
        nb = await repo.create_notebook(a, "n")
        doc = await repo.add_document(nb.id, "f.pdf", "application/pdf", 1, "s1")
        await repo.set_status(doc.id, tables.FAILED, reason="no_text")

        assert await repo.busy(nb.id) is False


class TestChunks:
    async def test_replacing_chunks_does_not_grow(self, session: AsyncSession) -> None:
        repo = NotebookRepository(session)
        a = await _owner(session, "a@x.com")
        nb = await repo.create_notebook(a, "n")
        doc_id = await _ready_doc(repo, nb.id, "s1")
        two = [NewChunk(i, f"t{i}", "", 1, 1, 1) for i in range(2)]

        await repo.replace_chunks(doc_id, two)
        await repo.replace_chunks(doc_id, two)

        assert await repo.count_chunks(doc_id) == 2

    async def test_duplicates_are_per_notebook(self, session: AsyncSession) -> None:
        repo = NotebookRepository(session)
        a = await _owner(session, "a@x.com")
        one, two = await repo.create_notebook(a, "1"), await repo.create_notebook(a, "2")
        await repo.add_document(one.id, "f.pdf", "application/pdf", 1, "same")

        assert await repo.duplicate(one.id, "same") is True
        assert await repo.duplicate(two.id, "same") is False


class TestWatchdog:
    async def test_stuck_parsing_becomes_failed_timeout(self, session: AsyncSession) -> None:
        repo = NotebookRepository(session)
        a = await _owner(session, "a@x.com")
        nb = await repo.create_notebook(a, "n")
        doc = await repo.add_document(nb.id, "f.pdf", "application/pdf", 1, "s1")
        await repo.start_parsing(doc.id)
        await session.execute(
            update(tables.Document)
            .where(tables.Document.id == doc.id)
            .values(updated_at=text("now() - interval '1 hour'"))
        )

        assert await repo.fail_stuck_parsing(timedelta(minutes=10)) == 1
        after = await repo.document(doc.id)
        assert after is not None
        assert (after.status, after.fail_reason) == (tables.FAILED, "timeout")
        assert await repo.busy(nb.id) is False
