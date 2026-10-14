"""A user's document store: ownership, upload limits, disable, rename, delete. No HTTP here."""

import hashlib
import io
from dataclasses import dataclass

import filetype
from sqlalchemy.exc import IntegrityError

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
from mycel.services import enqueue

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MARKDOWN = "text/markdown"


class DocumentError(Exception):
    """A refusal, with a sentence for the user. The api maps each kind to a status."""


class DocumentNotFound(DocumentError):
    def __init__(self) -> None:
        super().__init__("Not found.")


class UnsupportedType(DocumentError):
    pass


class TooLarge(DocumentError):
    pass


class Unusable(DocumentError):
    """Empty, or nameless: nothing to work with."""


class Conflict(DocumentError):
    """Already there, or no room left."""


class Busy(DocumentError):
    """Too much in flight; the same request works shortly."""


@dataclass(frozen=True, slots=True)
class Upload:
    filename: str
    data: bytes


def sniff(filename: str, data: bytes) -> str:
    """The real type of the file, from its bytes. `UnsupportedType` for anything else."""
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
    raise UnsupportedType("Only PDF, DOCX and Markdown files are supported.")


def max_bytes() -> int:
    return get_settings().document_max_bytes


async def list_documents(user_id: int) -> list[DocumentRow]:
    async with session_scope() as session:
        return await DocumentRepository(session).documents(user_id)


async def upload(user_id: int, file: Upload) -> DocumentRow:
    """Check, store the original, record it, queue the ingest job."""
    settings = get_settings()
    if len(file.data) > settings.document_max_bytes:
        raise TooLarge("Files are limited to 2 MB.")
    if not file.data:
        raise Unusable("The file is empty.")
    mime = sniff(file.filename, file.data)
    sha = hashlib.sha256(file.data).hexdigest()
    filename = _safe_name(file.filename)

    try:
        async with session_scope() as session:
            repo = DocumentRepository(session)
            same = await repo.duplicate(user_id, sha)
            if same is not None and same.status == DELETING:
                # The unique key still holds the old row until its delete job runs.
                raise Busy("That file is still being removed. Try again shortly.")
            if same is not None:
                raise Conflict("Already uploaded.")
            if await repo.count_documents(user_id) >= settings.documents_per_user:
                raise Conflict("You have reached the document limit.")
            if await repo.count_in_flight(user_id) >= settings.documents_in_flight_per_user:
                raise Busy("Too many documents are processing. Try again shortly.")
            doc = await repo.add_document(user_id, filename, mime, len(file.data), sha)
            await files.put(buckets.documents(), doc.object_key, io.BytesIO(file.data), mime)
            job = await enqueue.stage(session, enqueue.ingest_job(doc.id))
    except IntegrityError as exc:
        # The same file in two requests at once: both passed `duplicate`, one insert lost.
        raise Conflict("Already uploaded.") from exc

    await document_events.changed(user_id)
    await enqueue.send(job)
    return doc


async def rename(user_id: int, document_id: int, filename: str) -> DocumentRow:
    """A new display name. Search and citations show it at once; nothing is re-processed."""
    name = _safe_name(filename)
    if not name.strip():
        raise Unusable("A document needs a name.")
    async with session_scope() as session:
        repo = DocumentRepository(session)
        doc = await repo.owned_document(document_id, user_id)
        if doc is None or doc.status == DELETING:
            raise DocumentNotFound()
        await repo.rename(document_id, name)
        updated = await repo.document(document_id)
    assert updated is not None
    await document_events.changed(user_id)
    return updated


async def set_enabled(user_id: int, document_id: int, enabled: bool) -> DocumentRow:
    """Qdrant first, then Postgres: if Qdrant fails, the row still says what search does."""
    async with session_scope() as session:
        repo = DocumentRepository(session)
        doc = await repo.owned_document(document_id, user_id)
        if doc is None or doc.status == DELETING:
            raise DocumentNotFound()
    await vectors.set_enabled(document_id, enabled)
    async with session_scope() as session:
        repo = DocumentRepository(session)
        await repo.set_enabled(document_id, enabled)
        updated = await repo.document(document_id)
    assert updated is not None
    await document_events.changed(user_id)
    return updated


async def delete_document(user_id: int, document_id: int) -> None:
    """Hidden from search at once; the worker removes points, file and row after."""
    async with session_scope() as session:
        repo = DocumentRepository(session)
        doc = await repo.owned_document(document_id, user_id)
        if doc is None:
            raise DocumentNotFound()
        await repo.set_status(document_id, DELETING)
        job = await enqueue.stage(session, enqueue.delete_job(document_id))
    await document_events.changed(user_id)
    await enqueue.send(job)


async def source_url(user_id: int, document_id: int) -> str:
    async with session_scope() as session:
        doc = await DocumentRepository(session).owned_document(document_id, user_id)
    if doc is None or doc.status == DELETING:
        raise DocumentNotFound()
    return await presign(buckets.documents(), doc.object_key)


async def chunk(user_id: int, chunk_id: int) -> ChunkRow:
    async with session_scope() as session:
        found = await DocumentRepository(session).readable_chunks([chunk_id], user_id)
    if not found:
        raise DocumentNotFound()
    return found[0]


def _safe_name(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip() or "document"
    return "".join(c for c in name if c.isprintable())[:200]
