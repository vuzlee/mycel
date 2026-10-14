"""Upload refusals that depend on what else is happening: a race, a delete in progress."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from mycel.infra.postgres.documents import DELETING
from mycel.infra.redis import document_events
from mycel.infra.vectors import documents as vectors
from mycel.services import documents

pytestmark = pytest.mark.anyio

PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _repo(monkeypatch: pytest.MonkeyPatch, same: Any = None, insert_fails: bool = False) -> None:
    class Repo:
        def __init__(self, session: Any) -> None:
            pass

        async def duplicate(self, user_id: int, sha: str) -> Any:
            return same

        async def count_documents(self, user_id: int) -> int:
            return 0

        async def count_in_flight(self, user_id: int) -> int:
            return 0

        async def add_document(self, *args: Any) -> Any:
            if insert_fails:
                raise IntegrityError("INSERT", {}, Exception("uq_document_user_sha256"))
            return SimpleNamespace(id=1, object_key="k")

    @asynccontextmanager
    async def scope() -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(documents, "DocumentRepository", Repo)
    monkeypatch.setattr(documents, "session_scope", scope)


async def test_the_same_file_twice_at_once_is_a_conflict_not_a_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both requests passed the duplicate check; the unique key refused the second."""
    _repo(monkeypatch, insert_fails=True)

    with pytest.raises(documents.Conflict):
        await documents.upload(1, documents.Upload("f.pdf", PDF))


async def test_a_file_still_being_deleted_asks_to_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not "already uploaded": the list no longer shows it."""
    _repo(monkeypatch, same=SimpleNamespace(status=DELETING))

    with pytest.raises(documents.Busy):
        await documents.upload(1, documents.Upload("f.pdf", PDF))


async def test_toggling_writes_qdrant_before_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Qdrant failure must leave the row saying what search actually does."""
    order: list[str] = []

    class Repo:
        def __init__(self, session: Any) -> None:
            pass

        async def owned_document(self, document_id: int, user_id: int) -> Any:
            return SimpleNamespace(status="ready")

        async def set_enabled(self, document_id: int, enabled: bool) -> None:
            order.append("postgres")

        async def document(self, document_id: int) -> Any:
            return SimpleNamespace()

    @asynccontextmanager
    async def scope() -> AsyncIterator[None]:
        yield None

    async def qdrant(document_id: int, enabled: bool) -> None:
        order.append("qdrant")

    async def changed(user_id: int) -> None:
        pass

    monkeypatch.setattr(documents, "DocumentRepository", Repo)
    monkeypatch.setattr(documents, "session_scope", scope)
    monkeypatch.setattr(vectors, "set_enabled", qdrant)
    monkeypatch.setattr(document_events, "changed", changed)

    await documents.set_enabled(1, 1, False)

    assert order == ["qdrant", "postgres"]
