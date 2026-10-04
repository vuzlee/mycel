"""Notebook rules: ownership, upload limits, disable, delete. No HTTP here.

Every error is an English sentence the page can show as is.
"""

import hashlib
import io
from dataclasses import dataclass

import filetype

from mycel.core.config import get_settings
from mycel.infra.objects import buckets, files
from mycel.infra.objects.client import presign
from mycel.infra.postgres.notebooks import DELETING
from mycel.infra.postgres.repositories.notebooks import (
    ChunkRow,
    DocumentRow,
    NotebookRepository,
    NotebookRow,
)
from mycel.infra.postgres.session import session_scope
from mycel.infra.vectors import documents as vectors
from mycel.queue.producer import publish

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MARKDOWN = "text/markdown"


class NotebookError(Exception):
    """A refusal with an HTTP status and a sentence for the user."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _not_found() -> NotebookError:
    return NotebookError(404, "Not found.")


@dataclass(frozen=True, slots=True)
class Upload:
    filename: str
    data: bytes


def sniff(filename: str, data: bytes) -> str:
    """The real type of the file, from its bytes. Raises 415 for anything else."""
    kind = filetype.guess(data)
    if kind is not None and kind.mime == PDF:
        return PDF
    if kind is not None and kind.extension == "docx":
        return DOCX
    if kind is None and filename.lower().endswith((".md", ".markdown")):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            return MARKDOWN
    raise NotebookError(415, "Only PDF, DOCX and Markdown files are supported.")


async def create(owner_id: int, name: str) -> NotebookRow:
    name = name.strip()
    if not name:
        raise NotebookError(422, "A notebook needs a name.")
    async with session_scope() as session:
        repo = NotebookRepository(session)
        if await repo.count_notebooks(owner_id) >= get_settings().notebooks_per_user:
            raise NotebookError(409, "You have reached the notebook limit.")
        return await repo.create_notebook(owner_id, name[:120])


def max_bytes() -> int:
    return get_settings().document_max_bytes


async def list_notebooks(owner_id: int) -> list[NotebookRow]:
    async with session_scope() as session:
        return await NotebookRepository(session).notebooks(owner_id)


async def owned(owner_id: int, notebook_id: int) -> NotebookRow:
    async with session_scope() as session:
        found = await NotebookRepository(session).notebook(notebook_id, owner_id)
    if found is None:
        raise _not_found()
    return found


async def list_documents(owner_id: int, notebook_id: int) -> list[DocumentRow]:
    await owned(owner_id, notebook_id)
    async with session_scope() as session:
        return await NotebookRepository(session).documents(notebook_id)


async def upload(owner_id: int, notebook_id: int, file: Upload) -> DocumentRow:
    """Check, store the original, record it, queue the ingest job."""
    from mycel.domains.ingest import ingest_job

    settings = get_settings()
    if len(file.data) > settings.document_max_bytes:
        raise NotebookError(413, "Files are limited to 2 MB.")
    if not file.data:
        raise NotebookError(422, "The file is empty.")
    mime = sniff(file.filename, file.data)
    sha = hashlib.sha256(file.data).hexdigest()
    filename = _safe_name(file.filename)

    async with session_scope() as session:
        repo = NotebookRepository(session)
        if await repo.notebook(notebook_id, owner_id) is None:
            raise _not_found()
        if await repo.duplicate(notebook_id, sha):
            raise NotebookError(409, "Already uploaded.")
        if await repo.count_documents(notebook_id) >= settings.documents_per_notebook:
            raise NotebookError(409, "This notebook is full.")
        if await repo.count_in_flight(owner_id) >= settings.documents_in_flight_per_user:
            raise NotebookError(429, "Too many documents are processing. Try again shortly.")
        doc = await repo.add_document(notebook_id, filename, mime, len(file.data), sha)
        await files.put(buckets.documents(), doc.object_key, io.BytesIO(file.data), mime)

    await publish(ingest_job(doc.id))
    return doc


async def set_enabled(owner_id: int, document_id: int, enabled: bool) -> DocumentRow:
    """Postgres first, then the Qdrant payload. Vectors are never deleted here."""
    async with session_scope() as session:
        repo = NotebookRepository(session)
        doc = await repo.owned_document(document_id, owner_id)
        if doc is None or doc.status == DELETING:
            raise _not_found()
        await repo.set_enabled(document_id, enabled)
    await vectors.set_enabled(document_id, enabled)
    async with session_scope() as session:
        updated = await NotebookRepository(session).document(document_id)
    assert updated is not None
    return updated


async def delete_document(owner_id: int, document_id: int) -> None:
    """Hidden from search at once; the worker removes points, file and row after."""
    from mycel.domains.ingest import delete_job

    async with session_scope() as session:
        repo = NotebookRepository(session)
        doc = await repo.owned_document(document_id, owner_id)
        if doc is None:
            raise _not_found()
        await repo.set_status(document_id, DELETING)
    await publish(delete_job(document_id))


async def delete_notebook(owner_id: int, notebook_id: int) -> None:
    """Every document through the delete job, then the notebook row."""
    from mycel.domains.ingest import delete_job

    async with session_scope() as session:
        repo = NotebookRepository(session)
        if await repo.notebook(notebook_id, owner_id) is None:
            raise _not_found()
        docs = await repo.documents(notebook_id)
        for doc in docs:
            await repo.set_status(doc.id, DELETING)
    for doc in docs:
        await vectors.delete(doc.id)
        await files.delete(buckets.documents(), doc.object_key)
    async with session_scope() as session:
        await NotebookRepository(session).delete_notebook(notebook_id)
    for doc in docs:
        await publish(delete_job(doc.id))


async def source_url(owner_id: int, document_id: int) -> str:
    async with session_scope() as session:
        doc = await NotebookRepository(session).owned_document(document_id, owner_id)
    if doc is None or doc.status == DELETING:
        raise _not_found()
    return await presign(buckets.documents(), doc.object_key)


async def chunk(owner_id: int, chunk_id: int) -> ChunkRow:
    async with session_scope() as session:
        found = await NotebookRepository(session).readable_chunks([chunk_id], owner_id)
    if not found:
        raise _not_found()
    return found[0]


def _safe_name(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip() or "document"
    return "".join(c for c in name if c.isprintable())[:200]
