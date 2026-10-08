"""One person's conversations, for the sidebar."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from mycel.api.dependencies import CurrentUser
from mycel.services import conversations as domain
from mycel.services.conversations import HISTORY_LIMIT

router = APIRouter(tags=["conversations"])


class ConversationResponse(BaseModel):
    """One row in the sidebar."""

    id: int
    kind: str
    title: str
    created_at: datetime
    pinned: bool = False
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
            job_id=t.job_id,
            status=t.status,
        )
        for t in summaries
    ]


@router.get("/conversations/{conversation_id}/turns", response_model=list[TurnResponse])
async def list_turns(conversation_id: int, user: CurrentUser) -> list[TurnResponse]:
    """Every run in one conversation, oldest first."""
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


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: int, user: CurrentUser) -> Response:
    """Forget a conversation. The turns under it go too, by cascade."""
    if not await domain.forget_conversation(user.id, conversation_id):
        raise HTTPException(status_code=404, detail="no such conversation")
    return Response(status_code=204)
