"""Document SQL against a real Postgres: ownership, busy, chunk reads, the watchdog."""

from datetime import timedelta

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres import documents as tables
from mycel.infra.postgres.models import Document
from mycel.infra.postgres.repositories.documents import DocumentRepository, NewChunk
from mycel.infra.postgres.repositories.identity import IdentityRepository
from tests.fakes import needs_postgres

pytestmark = [
    pytest.mark.anyio,
    needs_postgres,
]


async def _owner(session: AsyncSession, email: str) -> int:
    return (await IdentityRepository(session).create_user(email)).id


async def _ready_doc(repo: DocumentRepository, user_id: int, sha: str) -> int:
    doc = await repo.add_document(user_id, f"{sha}.pdf", "application/pdf", 10, sha)
    await repo.replace_chunks(doc.id, [NewChunk(0, "text", "", 1, 1, 1)])
    await repo.set_status(doc.id, tables.READY)
    return doc.id


class TestOwnership:
    async def test_someone_elses_document_is_not_found(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        a, b = await _owner(session, "a@x.com"), await _owner(session, "b@x.com")
        doc_id = await _ready_doc(repo, a, "s1")

        assert await repo.owned_document(doc_id, a) is not None
        assert await repo.owned_document(doc_id, b) is None

    async def test_someone_elses_chunk_is_not_readable(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        a, b = await _owner(session, "a@x.com"), await _owner(session, "b@x.com")
        doc_id = await _ready_doc(repo, a, "s1")
        ids = await repo.replace_chunks(doc_id, [NewChunk(0, "hello", "", 1, 1, 1)])

        assert [c.text for c in await repo.readable_chunks(ids, a)] == ["hello"]
        assert await repo.readable_chunks(ids, b) == []

    async def test_each_user_lists_only_their_own(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        a, b = await _owner(session, "a@x.com"), await _owner(session, "b@x.com")
        await _ready_doc(repo, a, "s1")
        await _ready_doc(repo, b, "s2")

        assert [d.sha256 for d in await repo.documents(a)] == ["s1"]


class TestLayerTwo:
    async def test_a_disabled_document_has_no_readable_chunks(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        a = await _owner(session, "a@x.com")
        doc_id = await _ready_doc(repo, a, "s1")
        ids = await repo.replace_chunks(doc_id, [NewChunk(0, "t", "", 1, 1, 1)])

        await repo.set_enabled(doc_id, False)

        assert await repo.readable_chunks(ids, a) == []

    async def test_a_deleting_document_has_no_readable_chunks(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        a = await _owner(session, "a@x.com")
        doc_id = await _ready_doc(repo, a, "s1")
        ids = await repo.replace_chunks(doc_id, [NewChunk(0, "t", "", 1, 1, 1)])

        await repo.set_status(doc_id, tables.DELETING)

        assert await repo.readable_chunks(ids, a) == []


class TestBusy:
    async def test_busy_while_any_of_the_users_documents_is_in_flight(
        self, session: AsyncSession
    ) -> None:
        repo = DocumentRepository(session)
        a, b = await _owner(session, "a@x.com"), await _owner(session, "b@x.com")
        await repo.add_document(a, "f.pdf", "application/pdf", 1, "s1")

        assert await repo.busy(a) is True
        assert await repo.busy(b) is False

    async def test_a_failed_document_does_not_lock(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        a = await _owner(session, "a@x.com")
        doc = await repo.add_document(a, "f.pdf", "application/pdf", 1, "s1")
        await repo.set_status(doc.id, tables.FAILED, reason="no_text")

        assert await repo.busy(a) is False


class TestChunks:
    async def test_replacing_chunks_does_not_grow(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        a = await _owner(session, "a@x.com")
        doc_id = await _ready_doc(repo, a, "s1")
        two = [NewChunk(i, f"t{i}", "", 1, 1, 1) for i in range(2)]

        await repo.replace_chunks(doc_id, two)
        await repo.replace_chunks(doc_id, two)

        assert await repo.count_chunks(doc_id) == 2

    async def test_duplicates_are_per_user(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        a, b = await _owner(session, "a@x.com"), await _owner(session, "b@x.com")
        await repo.add_document(a, "f.pdf", "application/pdf", 1, "same")

        assert await repo.duplicate(a, "same") is not None
        assert await repo.duplicate(b, "same") is None

    async def test_a_document_being_deleted_frees_its_slot(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        a = await _owner(session, "a@x.com")
        doc = await repo.add_document(a, "f.pdf", "application/pdf", 1, "s1")
        await repo.set_status(doc.id, tables.DELETING)

        assert await repo.count_documents(a) == 0


class TestWatchdog:
    async def test_stuck_parsing_becomes_failed_timeout(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        a = await _owner(session, "a@x.com")
        doc = await repo.add_document(a, "f.pdf", "application/pdf", 1, "s1")
        await repo.start_parsing(doc.id)
        await session.execute(
            update(Document)
            .where(Document.id == doc.id)
            .values(updated_at=text("now() - interval '1 hour'"))
        )

        assert await repo.fail_stuck_parsing(timedelta(minutes=10)) == 1
        after = await repo.document(doc.id)
        assert after is not None
        assert (after.status, after.fail_reason) == (tables.FAILED, "timeout")
        assert await repo.busy(a) is False

    async def test_a_document_still_queued_is_not_failed(self, session: AsyncSession) -> None:
        """A backlog is a queue, not a hang: its job would skip a row already failed."""
        repo = DocumentRepository(session)
        a = await _owner(session, "a@x.com")
        doc = await repo.add_document(a, "f.pdf", "application/pdf", 1, "s1")
        await _age(session, doc.id)

        assert await repo.fail_stuck_parsing(timedelta(minutes=10)) == 0
        after = await repo.document(doc.id)
        assert after is not None and after.status == tables.UPLOADED

    async def test_a_stuck_delete_is_resent_once_per_window(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        a = await _owner(session, "a@x.com")
        doc = await repo.add_document(a, "f.pdf", "application/pdf", 1, "s1")
        await repo.set_status(doc.id, tables.DELETING)
        await _age(session, doc.id)

        assert await repo.requeue_stuck_deletes(timedelta(minutes=10)) == [doc.id]
        assert await repo.requeue_stuck_deletes(timedelta(minutes=10)) == []


async def _age(session: AsyncSession, document_id: int) -> None:
    await session.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(updated_at=text("now() - interval '1 hour'"))
    )


class TestRename:
    async def test_rename_changes_the_name_only(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        a = await _owner(session, "a@x.com")
        doc = await repo.add_document(a, "old.pdf", "application/pdf", 1, "s1")

        await repo.rename(doc.id, "BERT paper.pdf")

        after = await repo.document(doc.id)
        assert after is not None
        assert (after.filename, after.object_key) == ("BERT paper.pdf", doc.object_key)
