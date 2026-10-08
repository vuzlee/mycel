"""SQL for a user's documents and chunks. Ownership is checked in every read."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.documents import DELETING, FAILED, IN_FLIGHT, PARSING, READY
from mycel.infra.postgres.models import Chunk, Document
from mycel.infra.postgres.repositories._result import rowcount


@dataclass(frozen=True, slots=True)
class DocumentRow:
    id: int
    user_id: int
    filename: str
    mime: str
    size: int
    sha256: str
    object_key: str
    status: str
    fail_reason: str | None
    enabled: bool
    pages: int | None
    attempts: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class NewChunk:
    ord: int
    text: str
    section_path: str
    page_start: int | None
    page_end: int | None
    tokens: int


@dataclass(frozen=True, slots=True)
class ChunkRow:
    id: int
    document_id: int
    user_id: int
    filename: str
    mime: str
    ord: int
    text: str
    section_path: str
    page_start: int | None
    page_end: int | None = None


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- the store ---

    async def busy(self, user_id: int) -> bool:
        """Whether a document is still processing, so the knowledge base cannot be asked."""
        return bool(await self.count_in_flight(user_id))

    async def version(self, user_id: int) -> str:
        """Changes whenever any of the user's documents changes."""
        newest = await self._session.scalar(
            select(func.max(Document.updated_at)).where(Document.user_id == user_id)
        )
        count = await self.count_documents(user_id)
        return f"{count}-{newest.timestamp() if newest else 0}"

    # --- documents ---

    async def add_document(
        self, user_id: int, filename: str, mime: str, size: int, sha256: str
    ) -> DocumentRow:
        row = Document(
            user_id=user_id,
            filename=filename,
            mime=mime,
            size=size,
            sha256=sha256,
            object_key="",
            status="uploaded",
            enabled=True,
            attempts=0,
        )
        self._session.add(row)
        await self._session.flush()
        row.object_key = f"users/{user_id}/{row.id}/{filename}"
        await self._session.flush()
        await self._session.refresh(row)
        return _document(row)

    async def documents(self, user_id: int) -> list[DocumentRow]:
        rows = await self._session.scalars(
            select(Document)
            .where(Document.user_id == user_id, Document.status != DELETING)
            .order_by(Document.id)
        )
        return [_document(r) for r in rows]

    async def document(self, document_id: int) -> DocumentRow | None:
        row = await self._session.get(Document, document_id)
        return _document(row) if row else None

    async def owned_document(self, document_id: int, user_id: int) -> DocumentRow | None:
        row = await self._session.scalar(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
        return _document(row) if row else None

    async def lock_document(self, document_id: int) -> DocumentRow | None:
        row = await self._session.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        return _document(row) if row else None

    async def duplicate(self, user_id: int, sha256: str) -> bool:
        return bool(
            await self._count(
                select(Document.id).where(Document.user_id == user_id, Document.sha256 == sha256)
            )
        )

    async def count_documents(self, user_id: int) -> int:
        return await self._count(select(Document.id).where(Document.user_id == user_id))

    async def count_in_flight(self, user_id: int) -> int:
        return await self._count(
            select(Document.id).where(Document.user_id == user_id, Document.status.in_(IN_FLIGHT))
        )

    async def start_parsing(self, document_id: int) -> None:
        await self._session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(status=PARSING, attempts=Document.attempts + 1, updated_at=func.now())
        )

    async def set_status(
        self,
        document_id: int,
        status: str,
        *,
        reason: str | None = None,
        pages: int | None = None,
    ) -> None:
        values: dict[str, object] = {
            "status": status,
            "fail_reason": reason,
            "updated_at": func.now(),
        }
        if pages is not None:
            values["pages"] = pages
        await self._session.execute(
            update(Document).where(Document.id == document_id).values(**values)
        )

    async def rename(self, document_id: int, filename: str) -> None:
        """Rename for display; the object key keeps the original name."""
        await self._session.execute(
            update(Document).where(Document.id == document_id).values(filename=filename)
        )

    async def set_enabled(self, document_id: int, enabled: bool) -> None:
        await self._session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(enabled=enabled, updated_at=func.now())
        )

    async def delete_document(self, document_id: int) -> None:
        await self._session.execute(delete(Document).where(Document.id == document_id))

    async def stuck(self, status: str, older_than: timedelta) -> list[DocumentRow]:
        """Documents left in `status` longer than they should take."""
        rows = await self._session.scalars(
            select(Document).where(
                Document.status == status,
                Document.updated_at < func.now() - older_than,
            )
        )
        return [_document(r) for r in rows]

    async def fail_stuck_parsing(self, older_than: timedelta) -> int:
        result = await self._session.execute(
            update(Document)
            .where(
                Document.status.in_(IN_FLIGHT),
                Document.updated_at < func.now() - older_than,
            )
            .values(status=FAILED, fail_reason="timeout", updated_at=func.now())
        )
        return rowcount(result)

    # --- chunks ---

    async def replace_chunks(self, document_id: int, chunks: Sequence[NewChunk]) -> list[int]:
        """Replace a document's chunks; return the new ids in `ord` order."""
        await self._session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        rows = [
            Chunk(
                document_id=document_id,
                ord=c.ord,
                text=c.text,
                section_path=c.section_path,
                page_start=c.page_start,
                page_end=c.page_end,
                tokens=c.tokens,
            )
            for c in chunks
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return [r.id for r in rows]

    async def count_chunks(self, document_id: int) -> int:
        return await self._count(select(Chunk.id).where(Chunk.document_id == document_id))

    async def readable_chunks(self, chunk_ids: Sequence[int], user_id: int) -> list[ChunkRow]:
        """Chunks the owner may read now: their document, ready and enabled."""
        if not chunk_ids:
            return []
        rows = await self._session.execute(
            select(Chunk, Document)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.id.in_(list(chunk_ids)),
                Document.user_id == user_id,
                Document.status == READY,
                Document.enabled.is_(True),
            )
        )
        found = {c.id: _chunk(c, d) for c, d in rows.tuples()}
        return [found[i] for i in chunk_ids if i in found]

    async def _count(self, query: Select[Any]) -> int:
        total = await self._session.scalar(select(func.count()).select_from(query.subquery()))
        return int(total or 0)


def _document(row: Document) -> DocumentRow:
    return DocumentRow(
        row.id,
        row.user_id,
        row.filename,
        row.mime,
        row.size,
        row.sha256,
        row.object_key,
        row.status,
        row.fail_reason,
        row.enabled,
        row.pages,
        row.attempts,
        row.updated_at,
    )


def _chunk(row: Chunk, doc: Document) -> ChunkRow:
    return ChunkRow(
        row.id,
        row.document_id,
        doc.user_id,
        doc.filename,
        doc.mime,
        row.ord,
        row.text,
        row.section_path,
        row.page_start,
        row.page_end,
    )
