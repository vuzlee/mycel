"""All SQL for notebooks, documents and chunks. Ownership is checked in every read."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.notebooks import (
    DELETING,
    FAILED,
    IN_FLIGHT,
    PARSING,
    READY,
    Chunk,
    Document,
    Notebook,
)


@dataclass(frozen=True, slots=True)
class NotebookRow:
    id: int
    owner_id: int
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DocumentRow:
    id: int
    notebook_id: int
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
    notebook_id: int
    filename: str
    mime: str
    ord: int
    text: str
    section_path: str
    page_start: int | None


class NotebookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- notebooks ---

    async def create_notebook(self, owner_id: int, name: str) -> NotebookRow:
        row = Notebook(owner_id=owner_id, name=name)
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return _notebook(row)

    async def notebooks(self, owner_id: int) -> list[NotebookRow]:
        rows = await self._session.scalars(
            select(Notebook).where(Notebook.owner_id == owner_id).order_by(Notebook.id)
        )
        return [_notebook(r) for r in rows]

    async def notebook(self, notebook_id: int, owner_id: int) -> NotebookRow | None:
        """`None` both when it does not exist and when it is someone else's."""
        row = await self._session.scalar(
            select(Notebook).where(Notebook.id == notebook_id, Notebook.owner_id == owner_id)
        )
        return _notebook(row) if row else None

    async def count_notebooks(self, owner_id: int) -> int:
        return await self._count(select(Notebook.id).where(Notebook.owner_id == owner_id))

    async def delete_notebook(self, notebook_id: int) -> None:
        await self._session.execute(delete(Notebook).where(Notebook.id == notebook_id))

    async def busy(self, notebook_id: int) -> bool:
        """A document is still being processed, so the notebook cannot be asked."""
        return bool(
            await self._count(
                select(Document.id).where(
                    Document.notebook_id == notebook_id, Document.status.in_(IN_FLIGHT)
                )
            )
        )

    async def version(self, notebook_id: int) -> str:
        """Changes whenever any document in the notebook changes."""
        newest = await self._session.scalar(
            select(func.max(Document.updated_at)).where(Document.notebook_id == notebook_id)
        )
        count = await self.count_documents(notebook_id)
        return f"{count}-{newest.timestamp() if newest else 0}"

    # --- documents ---

    async def add_document(
        self, notebook_id: int, filename: str, mime: str, size: int, sha256: str
    ) -> DocumentRow:
        row = Document(
            notebook_id=notebook_id,
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
        row.object_key = f"notebooks/{notebook_id}/{row.id}/{filename}"
        await self._session.flush()
        await self._session.refresh(row)
        return _document(row)

    async def documents(self, notebook_id: int) -> list[DocumentRow]:
        rows = await self._session.scalars(
            select(Document)
            .where(Document.notebook_id == notebook_id, Document.status != DELETING)
            .order_by(Document.id)
        )
        return [_document(r) for r in rows]

    async def document(self, document_id: int) -> DocumentRow | None:
        row = await self._session.get(Document, document_id)
        return _document(row) if row else None

    async def owned_document(self, document_id: int, owner_id: int) -> DocumentRow | None:
        row = await self._session.scalar(
            select(Document)
            .join(Notebook, Notebook.id == Document.notebook_id)
            .where(Document.id == document_id, Notebook.owner_id == owner_id)
        )
        return _document(row) if row else None

    async def lock_document(self, document_id: int) -> DocumentRow | None:
        """The row, locked until this transaction ends."""
        row = await self._session.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        return _document(row) if row else None

    async def duplicate(self, notebook_id: int, sha256: str) -> bool:
        return bool(
            await self._count(
                select(Document.id).where(
                    Document.notebook_id == notebook_id, Document.sha256 == sha256
                )
            )
        )

    async def count_documents(self, notebook_id: int) -> int:
        return await self._count(select(Document.id).where(Document.notebook_id == notebook_id))

    async def count_in_flight(self, owner_id: int) -> int:
        return await self._count(
            select(Document.id)
            .join(Notebook, Notebook.id == Document.notebook_id)
            .where(Notebook.owner_id == owner_id, Document.status.in_(IN_FLIGHT))
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
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    # --- chunks ---

    async def replace_chunks(self, document_id: int, chunks: Sequence[NewChunk]) -> list[int]:
        """Drop the old chunks, write the new ones, return their ids in `ord` order."""
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

    async def readable_chunks(self, chunk_ids: Sequence[int], owner_id: int) -> list[ChunkRow]:
        """Chunks the owner may read right now: own notebook, document ready and enabled."""
        if not chunk_ids:
            return []
        rows = await self._session.execute(
            select(Chunk, Document, Notebook)
            .join(Document, Document.id == Chunk.document_id)
            .join(Notebook, Notebook.id == Document.notebook_id)
            .where(
                Chunk.id.in_(list(chunk_ids)),
                Notebook.owner_id == owner_id,
                Document.status == READY,
                Document.enabled.is_(True),
            )
        )
        found = {c.id: _chunk(c, d) for c, d, _ in rows.tuples()}
        return [found[i] for i in chunk_ids if i in found]

    async def _count(self, query: Select[Any]) -> int:
        total = await self._session.scalar(select(func.count()).select_from(query.subquery()))
        return int(total or 0)


def _notebook(row: Notebook) -> NotebookRow:
    return NotebookRow(row.id, row.owner_id, row.name, row.created_at)


def _document(row: Document) -> DocumentRow:
    return DocumentRow(
        row.id,
        row.notebook_id,
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
        doc.notebook_id,
        doc.filename,
        doc.mime,
        row.ord,
        row.text,
        row.section_path,
        row.page_start,
    )
