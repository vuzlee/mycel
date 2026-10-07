"""A user's document store: ownership, upload limits, disable, rename, delete. No HTTP here.

Every error is an English sentence the page can show as is.
"""

import hashlib
import io
from dataclasses import dataclass

import filetype

from mycel.core.config import get_settings
from mycel.infra.objects import buckets, files
from mycel.infra.objects.client import presign
from mycel.infra.postgres.documents import DELETING
from mycel.infra.postgres.repositories.documents import (
    ChunkRow,
    DocumentRepository,
    DocumentRow,
)
from mycel.infra.postgres.session import session_scope
from mycel.infra.redis import document_events
from mycel.infra.vectors import documents as vectors
from mycel.queue.producer import publish
from mycel.services.enqueue import delete_job, ingest_job

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MARKDOWN = "text/markdown"


class DocumentError(Exception):
    """A refusal with an HTTP status and a sentence for the user."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _not_found() -> DocumentError:
    return DocumentError(404, "Not found.")


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
    raise DocumentError(415, "Only PDF, DOCX and Markdown files are supported.")


def max_bytes() -> int:
    return get_settings().document_max_bytes


async def list_documents(user_id: int) -> list[DocumentRow]:
    async with session_scope() as session:
        return await DocumentRepository(session).documents(user_id)


async def busy(user_id: int) -> bool:
    """Whether any of the user's documents is still being processed."""
    async with session_scope() as session:
        return await DocumentRepository(session).busy(user_id)


async def upload(user_id: int, file: Upload) -> DocumentRow:
    """Check, store the original, record it, queue the ingest job."""
    settings = get_settings()
    if len(file.data) > settings.document_max_bytes:
        raise DocumentError(413, "Files are limited to 2 MB.")
    if not file.data:
        raise DocumentError(422, "The file is empty.")
    mime = sniff(file.filename, file.data)
    sha = hashlib.sha256(file.data).hexdigest()
    filename = _safe_name(file.filename)

    async with session_scope() as session:
        repo = DocumentRepository(session)
        if await repo.duplicate(user_id, sha):
            raise DocumentError(409, "Already uploaded.")
        if await repo.count_documents(user_id) >= settings.documents_per_user:
            raise DocumentError(409, "You have reached the document limit.")
        if await repo.count_in_flight(user_id) >= settings.documents_in_flight_per_user:
            raise DocumentError(429, "Too many documents are processing. Try again shortly.")
        doc = await repo.add_document(user_id, filename, mime, len(file.data), sha)
        await files.put(buckets.documents(), doc.object_key, io.BytesIO(file.data), mime)

    await document_events.changed(user_id)
    await publish(ingest_job(doc.id))
    return doc


async def rename(user_id: int, document_id: int, filename: str) -> DocumentRow:
    """A new display name. Search and citations show it at once; nothing is re-processed."""
    name = _safe_name(filename)
    if not name.strip():
        raise DocumentError(422, "A document needs a name.")
    async with session_scope() as session:
        repo = DocumentRepository(session)
        doc = await repo.owned_document(document_id, user_id)
        if doc is None or doc.status == DELETING:
            raise _not_found()
        await repo.rename(document_id, name)
        updated = await repo.document(document_id)
    assert updated is not None
    await document_events.changed(user_id)
    return updated


async def set_enabled(user_id: int, document_id: int, enabled: bool) -> DocumentRow:
    """Postgres first, then the Qdrant payload. Vectors are never deleted here."""
    async with session_scope() as session:
        repo = DocumentRepository(session)
        doc = await repo.owned_document(document_id, user_id)
        if doc is None or doc.status == DELETING:
            raise _not_found()
        await repo.set_enabled(document_id, enabled)
    await vectors.set_enabled(document_id, enabled)
    async with session_scope() as session:
        updated = await DocumentRepository(session).document(document_id)
    assert updated is not None
    await document_events.changed(user_id)
    return updated


async def delete_document(user_id: int, document_id: int) -> None:
    """Hidden from search at once; the worker removes points, file and row after."""
    async with session_scope() as session:
        repo = DocumentRepository(session)
        doc = await repo.owned_document(document_id, user_id)
        if doc is None:
            raise _not_found()
        await repo.set_status(document_id, DELETING)
    await document_events.changed(user_id)
    await publish(delete_job(document_id))


async def source_url(user_id: int, document_id: int) -> str:
    async with session_scope() as session:
        doc = await DocumentRepository(session).owned_document(document_id, user_id)
    if doc is None or doc.status == DELETING:
        raise _not_found()
    return await presign(buckets.documents(), doc.object_key)


async def chunk(user_id: int, chunk_id: int) -> ChunkRow:
    async with session_scope() as session:
        found = await DocumentRepository(session).readable_chunks([chunk_id], user_id)
    if not found:
        raise _not_found()
    return found[0]


def _safe_name(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip() or "document"
    return "".join(c for c in name if c.isprintable())[:200]
