"""A user's documents, which the Knowledge chip reads."""

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from mycel.api.dependencies import CurrentUser
from mycel.infra.postgres.repositories.documents import DocumentRow
from mycel.infra.redis import document_events
from mycel.services import documents as service

router = APIRouter(tags=["documents"])


class DocumentOut(BaseModel):
    id: int
    filename: str
    mime: str
    size: int
    status: str
    fail_reason: str | None
    enabled: bool
    pages: int | None


class DocumentPatch(BaseModel):
    """One change at a time: switch it on or off, or rename it."""

    enabled: bool | None = None
    filename: str | None = Field(default=None, min_length=1, max_length=200)


class SourceOut(BaseModel):
    url: str


class ChunkOut(BaseModel):
    id: int
    document_id: int
    filename: str
    text: str
    section_path: str
    page_start: int | None


def _document(row: DocumentRow) -> DocumentOut:
    return DocumentOut(
        id=row.id,
        filename=row.filename,
        mime=row.mime,
        size=row.size,
        status=row.status,
        fail_reason=row.fail_reason,
        enabled=row.enabled,
        pages=row.pages,
    )


def _refused(exc: service.DocumentError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


@router.post("/documents", response_model=DocumentOut, status_code=202)
async def upload_document(user: CurrentUser, file: Annotated[UploadFile, File()]) -> DocumentOut:
    data = await file.read(service.max_bytes() + 1)
    try:
        doc = await service.upload(user.id, service.Upload(file.filename or "document", data))
    except service.DocumentError as exc:
        raise _refused(exc) from exc
    return _document(doc)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(user: CurrentUser) -> list[DocumentOut]:
    return [_document(d) for d in await service.list_documents(user.id)]


@router.get("/documents/status")
async def document_status(request: Request, user: CurrentUser) -> StreamingResponse:
    """The user's document list, sent again whenever one of them changes state (SSE)."""
    return StreamingResponse(
        _status_frames(request, user.id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _status_frames(request: Request, user_id: int) -> AsyncIterator[str]:
    async def snapshot() -> str:
        docs = [_document(d).model_dump() for d in await service.list_documents(user_id)]
        busy = any(d["status"] in ("uploaded", "parsing") for d in docs)
        return f"data: {json.dumps({'busy': busy, 'documents': docs})}\n\n"

    # Subscribed before the first snapshot, so a change between the two is not lost.
    listener = await document_events.Listener(user_id).open()
    try:
        yield await snapshot()
        while not await request.is_disconnected():
            yield await snapshot() if await listener.next(timeout_s=15) else ": keepalive\n\n"
    finally:
        await listener.close()


@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def patch_document(document_id: int, body: DocumentPatch, user: CurrentUser) -> DocumentOut:
    try:
        doc = None
        if body.filename is not None:
            doc = await service.rename(user.id, document_id, body.filename)
        if body.enabled is not None:
            doc = await service.set_enabled(user.id, document_id, body.enabled)
    except service.DocumentError as exc:
        raise _refused(exc) from exc
    if doc is None:
        raise HTTPException(422, "Nothing to change.")
    return _document(doc)


@router.delete("/documents/{document_id}", status_code=202)
async def delete_document(document_id: int, user: CurrentUser) -> Response:
    try:
        await service.delete_document(user.id, document_id)
    except service.DocumentError as exc:
        raise _refused(exc) from exc
    return Response(status_code=202)


@router.get("/documents/{document_id}/source", response_model=SourceOut)
async def document_source(document_id: int, user: CurrentUser) -> SourceOut:
    try:
        return SourceOut(url=await service.source_url(user.id, document_id))
    except service.DocumentError as exc:
        raise _refused(exc) from exc


@router.get("/chunks/{chunk_id}", response_model=ChunkOut)
async def read_chunk(chunk_id: int, user: CurrentUser) -> ChunkOut:
    try:
        c = await service.chunk(user.id, chunk_id)
    except service.DocumentError as exc:
        raise _refused(exc) from exc
    return ChunkOut(
        id=c.id,
        document_id=c.document_id,
        filename=c.filename,
        text=c.text,
        section_path=c.section_path,
        page_start=c.page_start,
    )
