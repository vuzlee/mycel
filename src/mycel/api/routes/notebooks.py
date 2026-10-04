"""Notebooks and their documents.

    POST    /notebooks                      create
    GET     /notebooks                      list mine
    DELETE  /notebooks/{id}                 delete with every document
    POST    /notebooks/{id}/documents       upload one file
    GET     /notebooks/{id}/documents       list with status
    PATCH   /documents/{id}                 enable / disable
    DELETE  /documents/{id}                 delete
    GET     /documents/{id}/source          presigned URL to the original
    GET     /chunks/{id}                    one passage, for a citation
    POST    /notebooks/{id}/ask             ask a question (202, or 200 when cached)
    GET     /asks/{job_id}                  the answer and its sources
    GET     /asks/quota                     questions left today

Someone else's notebook, document or chunk is 404, never 403.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from mycel.api.dependencies import current_user
from mycel.domains import ask as ask_domain
from mycel.infra.postgres.repositories.notebooks import DocumentRow, NotebookRow
from mycel.services import notebooks as service
from mycel.services.auth import Principal

router = APIRouter(tags=["notebooks"])

Me = Annotated[Principal, Depends(current_user)]


class NotebookIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class NotebookOut(BaseModel):
    id: int
    name: str
    created_at: datetime


class DocumentOut(BaseModel):
    id: int
    notebook_id: int
    filename: str
    mime: str
    size: int
    status: str
    fail_reason: str | None
    enabled: bool
    pages: int | None


class EnabledIn(BaseModel):
    enabled: bool


class SourceOut(BaseModel):
    url: str


class ChunkOut(BaseModel):
    id: int
    document_id: int
    filename: str
    text: str
    section_path: str
    page_start: int | None


def _notebook(row: NotebookRow) -> NotebookOut:
    return NotebookOut(id=row.id, name=row.name, created_at=row.created_at)


def _document(row: DocumentRow) -> DocumentOut:
    return DocumentOut(
        id=row.id,
        notebook_id=row.notebook_id,
        filename=row.filename,
        mime=row.mime,
        size=row.size,
        status=row.status,
        fail_reason=row.fail_reason,
        enabled=row.enabled,
        pages=row.pages,
    )


def _refused(exc: service.NotebookError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


@router.post("/notebooks", response_model=NotebookOut, status_code=201)
async def create_notebook(body: NotebookIn, me: Me) -> NotebookOut:
    try:
        return _notebook(await service.create(me.id, body.name))
    except service.NotebookError as exc:
        raise _refused(exc) from exc


@router.get("/notebooks", response_model=list[NotebookOut])
async def list_notebooks(me: Me) -> list[NotebookOut]:
    return [_notebook(r) for r in await service.list_notebooks(me.id)]


@router.delete("/notebooks/{notebook_id}", status_code=204)
async def delete_notebook(notebook_id: int, me: Me) -> Response:
    try:
        await service.delete_notebook(me.id, notebook_id)
    except service.NotebookError as exc:
        raise _refused(exc) from exc
    return Response(status_code=204)


@router.post("/notebooks/{notebook_id}/documents", response_model=DocumentOut, status_code=202)
async def upload_document(
    notebook_id: int, me: Me, file: Annotated[UploadFile, File()]
) -> DocumentOut:
    data = await file.read(service.max_bytes() + 1)
    try:
        doc = await service.upload(
            me.id, notebook_id, service.Upload(file.filename or "document", data)
        )
    except service.NotebookError as exc:
        raise _refused(exc) from exc
    return _document(doc)


@router.get("/notebooks/{notebook_id}/documents", response_model=list[DocumentOut])
async def list_documents(notebook_id: int, me: Me) -> list[DocumentOut]:
    try:
        return [_document(d) for d in await service.list_documents(me.id, notebook_id)]
    except service.NotebookError as exc:
        raise _refused(exc) from exc


@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def set_enabled(document_id: int, body: EnabledIn, me: Me) -> DocumentOut:
    try:
        return _document(await service.set_enabled(me.id, document_id, body.enabled))
    except service.NotebookError as exc:
        raise _refused(exc) from exc


@router.delete("/documents/{document_id}", status_code=202)
async def delete_document(document_id: int, me: Me) -> Response:
    try:
        await service.delete_document(me.id, document_id)
    except service.NotebookError as exc:
        raise _refused(exc) from exc
    return Response(status_code=202)


@router.get("/documents/{document_id}/source", response_model=SourceOut)
async def document_source(document_id: int, me: Me) -> SourceOut:
    try:
        return SourceOut(url=await service.source_url(me.id, document_id))
    except service.NotebookError as exc:
        raise _refused(exc) from exc


@router.get("/chunks/{chunk_id}", response_model=ChunkOut)
async def read_chunk(chunk_id: int, me: Me) -> ChunkOut:
    try:
        c = await service.chunk(me.id, chunk_id)
    except service.NotebookError as exc:
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


@router.post("/notebooks/{notebook_id}/ask", response_model=AskOut, status_code=202)
async def ask(notebook_id: int, body: AskIn, me: Me, response: Response) -> AskOut:
    try:
        outcome = await ask_domain.request_ask(me.id, notebook_id, body.question)
    except service.NotebookError as exc:
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
    except service.NotebookError as exc:
        raise _refused(exc) from exc
    return AskOut(job_id=job_id, **state)
