"""One ingest job, and one delete job. Runs on the ingest worker only.

Order matters. Qdrant is written before Postgres marks the document ready, so a question
never sees a ready document whose passages cannot be found. Every step can run twice.
"""

import asyncio
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.objects import buckets, files
from mycel.infra.postgres.documents import DELETING, FAILED, READY
from mycel.infra.postgres.repositories.documents import DocumentRepository, NewChunk
from mycel.infra.postgres.session import session_scope
from mycel.infra.redis import document_events
from mycel.infra.vectors import documents as vectors
from mycel.queue.job import Job, JobKind
from mycel.queue.producer import publish

if TYPE_CHECKING:
    from mycel.infra.documents.chunk import Passage

log = get_logger(__name__)


def ingest_job(document_id: int) -> Job:
    return Job(kind=JobKind.INGEST, payload={"document_id": document_id})


def delete_job(document_id: int) -> Job:
    return Job(kind=JobKind.DELETE_DOCUMENT, payload={"document_id": document_id})


async def run(job: Job) -> None:
    document_id = int(str(job.payload["document_id"]))
    async with session_scope() as session:
        repo = DocumentRepository(session)
        doc = await repo.document(document_id)
        if doc is None or doc.status in (DELETING, READY):
            log.info("ingest skipped", extra={"document_id": document_id})
            return
        await repo.start_parsing(document_id)
    await document_events.changed(doc.owner_id)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / doc.filename
        await files.download(buckets.documents(), doc.object_key, path)
        parsed = await _parse_and_chunk(path)

    if isinstance(parsed, str):
        await _fail(document_id, parsed)
        return
    pages, passages = parsed

    await vectors.delete(document_id)
    async with session_scope() as session:
        repo = DocumentRepository(session)
        current = await repo.lock_document(document_id)
        if current is None or current.status == DELETING:
            await vectors.delete(document_id)
            return
        chunk_ids = await repo.replace_chunks(
            document_id,
            [
                NewChunk(i, p.text, p.section_path, p.page_start, p.page_end, p.tokens)
                for i, p in enumerate(passages)
            ],
        )
        await vectors.write(
            current.owner_id,
            document_id,
            current.enabled,
            chunk_ids,
            [p.text for p in passages],
        )
        await repo.set_status(document_id, READY, pages=pages)
    await document_events.changed(current.owner_id)
    log.info("document ready", extra={"document_id": document_id, "chunks": len(passages)})


async def delete(job: Job) -> None:
    """Points, then the file, then the row. Each step is already-done-safe."""
    document_id = int(str(job.payload["document_id"]))
    async with session_scope() as session:
        doc = await DocumentRepository(session).document(document_id)
    if doc is None:
        await vectors.delete(document_id)
        return
    await vectors.delete(document_id)
    await files.delete(buckets.documents(), doc.object_key)
    async with session_scope() as session:
        await DocumentRepository(session).delete_document(document_id)
    await document_events.changed(doc.owner_id)
    log.info("document deleted", extra={"document_id": document_id})


async def watchdog() -> None:
    """A dead worker leaves rows in flight forever; this unlocks them."""
    stuck = timedelta(seconds=get_settings().document_stuck_seconds)
    async with session_scope() as session:
        repo = DocumentRepository(session)
        failed = await repo.fail_stuck_parsing(stuck)
        deleting = await repo.stuck(DELETING, stuck)
    if failed:
        log.warning("stuck documents failed", extra={"count": failed})
    for doc in deleting:
        await publish(delete_job(doc.id))


async def record_failure(job: Job, error: str) -> None:
    """The last attempt failed: the row says so, and the knowledge base unlocks."""
    if job.kind is JobKind.INGEST:
        await _fail(int(str(job.payload["document_id"])), "error")
    log.error("ingest job failed", extra={"job": str(job.kind), "error": error[:300]})


async def _fail(document_id: int, reason: str) -> None:
    async with session_scope() as session:
        repo = DocumentRepository(session)
        doc = await repo.document(document_id)
        if doc is not None and doc.status != DELETING:
            await repo.set_status(document_id, FAILED, reason=reason)
    if doc is not None:
        await document_events.changed(doc.owner_id)
    log.warning("document failed", extra={"document_id": document_id, "reason": reason})


async def _parse_and_chunk(path: Path) -> "tuple[int, list[Passage]] | str":
    """`(pages, passages)`, or the failure reason. CPU-bound, so off the event loop."""
    from mycel.infra.documents.chunk import passages
    from mycel.infra.documents.parse import ParseError, parse

    def work() -> "tuple[int, list[Passage]] | str":
        try:
            doc = parse(path)
        except ParseError as exc:
            return exc.reason
        found = passages(doc)
        if not found:
            return "no_text"
        return int(doc.num_pages() or 0), found

    return await asyncio.to_thread(work)
