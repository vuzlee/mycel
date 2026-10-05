"""A user's documents, and asking them (the Knowledge chip).

    POST    /documents                      upload one file
    GET     /documents                      list mine, with status
    GET     /documents/status               busy or not, live (SSE)
    PATCH   /documents/{id}                 enable / disable, or rename
    DELETE  /documents/{id}                 delete
    GET     /documents/{id}/source          presigned URL to the original
    GET     /chunks/{id}                    one passage, for a citation
    POST    /knowledge/ask                  ask a question (202, or 200 when cached)
    GET     /asks/{job_id}                  the answer and its sources
    GET     /asks/quota                     questions left today

Someone else's document or chunk is 404, never 403.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from mycel.api.dependencies import current_user
from mycel.domains import ask as ask_domain
from mycel.infra.postgres.repositories.documents import DocumentRow
from mycel.services import documents as service
from mycel.services.auth import Principal

router = APIRouter(tags=["documents"])

Me = Annotated[Principal, Depends(current_user)]


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
async def upload_document(me: Me, file: Annotated[UploadFile, File()]) -> DocumentOut:
    data = await file.read(service.max_bytes() + 1)
    try:
        doc = await service.upload(me.id, service.Upload(file.filename or "document", data))
    except service.DocumentError as exc:
        raise _refused(exc) from exc
    return _document(doc)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(me: Me) -> list[DocumentOut]:
    return [_document(d) for d in await service.list_documents(me.id)]


@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def patch_document(document_id: int, body: DocumentPatch, me: Me) -> DocumentOut:
    try:
        doc = None
        if body.filename is not None:
            doc = await service.rename(me.id, document_id, body.filename)
        if body.enabled is not None:
            doc = await service.set_enabled(me.id, document_id, body.enabled)
    except service.DocumentError as exc:
        raise _refused(exc) from exc
    if doc is None:
        raise HTTPException(422, "Nothing to change.")
    return _document(doc)


@router.delete("/documents/{document_id}", status_code=202)
async def delete_document(document_id: int, me: Me) -> Response:
    try:
        await service.delete_document(me.id, document_id)
    except service.DocumentError as exc:
        raise _refused(exc) from exc
    return Response(status_code=202)


@router.get("/documents/{document_id}/source", response_model=SourceOut)
async def document_source(document_id: int, me: Me) -> SourceOut:
    try:
        return SourceOut(url=await service.source_url(me.id, document_id))
    except service.DocumentError as exc:
        raise _refused(exc) from exc


@router.get("/chunks/{chunk_id}", response_model=ChunkOut)
async def read_chunk(chunk_id: int, me: Me) -> ChunkOut:
    try:
        c = await service.chunk(me.id, chunk_id)
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


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    #: The question asked just before, so a follow-up can say "it". Optional.
    previous: str = Field(default="", max_length=2000)


class SourceRef(BaseModel):
    label: str
    chunk_id: int
    document_id: int
    filename: str
    mime: str
    page: int | None
    section: str


class AskOut(BaseModel):
    status: str
    job_id: str | None = None
    answer: str | None = None
    sources: list[SourceRef] = []
    error: str | None = None
    cached: bool = False


class QuotaOut(BaseModel):
    remaining: int


@router.post("/knowledge/ask", response_model=AskOut, status_code=202)
async def ask(body: AskIn, me: Me, response: Response) -> AskOut:
    try:
        outcome = await ask_domain.request_ask(me.id, body.question, body.previous)
    except service.DocumentError as exc:
        raise _refused(exc) from exc
    if outcome["cached"]:
        response.status_code = 200
        return AskOut(
            status="done", answer=outcome["answer"], sources=outcome["sources"], cached=True
        )
    return AskOut(status="queued", job_id=outcome["job_id"])


@router.get("/asks/quota", response_model=QuotaOut)
async def ask_quota(me: Me) -> QuotaOut:
    return QuotaOut(remaining=await ask_domain.remaining(me.id))


@router.get("/asks/{job_id}", response_model=AskOut)
async def ask_result(job_id: str, me: Me) -> AskOut:
    try:
        state = await ask_domain.read(me.id, job_id)
    except service.DocumentError as exc:
        raise _refused(exc) from exc
    return AskOut(job_id=job_id, **state)
