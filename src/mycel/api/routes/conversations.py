"""One person's conversations, for the sidebar."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from mycel.api.dependencies import CurrentUser
from mycel.services import conversations as domain
from mycel.services import model_catalog as models
from mycel.services.conversations import HISTORY_LIMIT

router = APIRouter(tags=["conversations"])


class ConversationResponse(BaseModel):
    """One row in the sidebar."""

    id: int
    kind: str
    title: str
    created_at: datetime
    pinned: bool = False
    archived: bool = False
    job_id: str | None = None
    status: str | None = None


class TurnResponse(BaseModel):
    """One run inside a conversation, as the page replays it."""

    job_id: str
    question: str
    status: str
    answer: str | None = None
    spent_usd: str | None = None
    error: str | None = None
    steps: list[dict[str, Any]] | None = None
    created_at: datetime
    model_ref: str | None = None
    model_label: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    duration_ms: int | None = None


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    user: CurrentUser,
    limit: int = Query(default=HISTORY_LIMIT, ge=1, le=HISTORY_LIMIT),
) -> list[ConversationResponse]:
    """This person's conversations, newest first."""
    summaries = await domain.list_conversations(user.id, limit)
    return [
        ConversationResponse(
            id=t.conversation.id,
            kind=t.conversation.kind,
            title=t.conversation.title,
            created_at=t.conversation.created_at,
            pinned=t.conversation.pinned_at is not None,
            archived=t.conversation.archived_at is not None,
            job_id=t.job_id,
            status=t.status,
        )
        for t in summaries
    ]


@router.get("/conversations/{conversation_id}/turns", response_model=list[TurnResponse])
async def list_turns(conversation_id: int, user: CurrentUser) -> list[TurnResponse]:
    """Every run in one conversation, oldest first."""
    labels = await models.labels_for(user.id)
    return [
        TurnResponse(
            job_id=turn.job_id,
            question=turn.question,
            status=turn.status,
            answer=turn.answer,
            spent_usd=str(turn.spent_usd) if turn.spent_usd is not None else None,
            error=turn.error,
            steps=turn.steps,
            created_at=turn.created_at,
            model_ref=turn.model_ref,
            model_label=labels.get(turn.model_ref, turn.model_ref) if turn.model_ref else None,
            tokens_in=turn.tokens_in,
            tokens_out=turn.tokens_out,
            duration_ms=turn.duration_ms,
        )
        for turn in await domain.conversation_turns(user.id, conversation_id)
    ]


class PinRequest(BaseModel):
    pinned: bool


@router.put("/conversations/{conversation_id}/pin", status_code=204)
async def pin_conversation(conversation_id: int, body: PinRequest, user: CurrentUser) -> Response:
    """Pin or unpin a conversation. 404 for "not yours" as well, same as the delete."""
    if not await domain.pin_conversation(user.id, conversation_id, body.pinned):
        raise HTTPException(status_code=404, detail="no such conversation")
    return Response(status_code=204)


class EditRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    archived: bool | None = None


@router.patch("/conversations/{conversation_id}", status_code=204)
async def edit_conversation(conversation_id: int, body: EditRequest, user: CurrentUser) -> Response:
    """Rename or archive a conversation. 404 for "not yours" as well."""
    title = body.title.strip() if body.title is not None else None
    if title == "" or (title is None and body.archived is None):
        raise HTTPException(status_code=422, detail="nothing to change")
    if not await domain.edit_conversation(
        user.id, conversation_id, title=title, archived=body.archived
    ):
        raise HTTPException(status_code=404, detail="no such conversation")
    return Response(status_code=204)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: int, user: CurrentUser) -> Response:
    """Forget a conversation. The turns under it go too, by cascade."""
    if not await domain.forget_conversation(user.id, conversation_id):
        raise HTTPException(status_code=404, detail="no such conversation")
    return Response(status_code=204)
