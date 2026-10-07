"""One person's conversations, for the sidebar.

    GET     /conversations             this person's conversations, for the sidebar
    GET     /conversations/{id}/turns  every run in one conversation, oldest first
    PUT     /conversations/{id}/pin    pin or unpin one, so it stays at the top
    DELETE  /conversations/{id}        forget one, and every run under it

Behind `current_user`: every row here is personal.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from mycel.api.dependencies import current_user
from mycel.domains import conversations as domain
from mycel.domains.conversations import HISTORY_LIMIT
from mycel.services.auth import Principal

router = APIRouter(tags=["conversations"])


class ConversationResponse(BaseModel):
    """One row in the sidebar.

    `job_id` is null for a conversation whose run has not produced anything yet. The page shows
    that as a queued run rather than hiding the row — a job the worker never picked up is
    exactly what someone needs to see.
    """

    id: int
    kind: str
    title: str
    created_at: datetime
    pinned: bool = False
    job_id: str | None = None
    status: str | None = None


class TurnResponse(BaseModel):
    """One run inside a conversation, as the page replays it.

    `answer` comes back whole rather than summarised: it is markdown the page already
    knows how to render, and shortening it here would be a second opinion about the same
    text.

    `steps` is the tool calls that turn made, in the same shape the live stream sends —
    so the page replays a finished turn with the builder it already has. Null for a turn
    recorded without steps, and for one that failed.
    """

    job_id: str
    question: str
    status: str
    answer: str | None = None
    spent_usd: str | None = None
    error: str | None = None
    steps: list[dict[str, Any]] | None = None
    created_at: datetime


@router.get("/conversations", response_model=list[ConversationResponse])
async def read_conversations(
    user: Annotated[Principal, Depends(current_user)],
    limit: int = Query(default=HISTORY_LIMIT, ge=1, le=HISTORY_LIMIT),
) -> list[ConversationResponse]:
    """This person's conversations, newest first. The sidebar, and it follows them to any
    browser — which is the whole reason `localStorage` stopped being where it lived."""
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
async def read_turns(
    conversation_id: int, user: Annotated[Principal, Depends(current_user)]
) -> list[TurnResponse]:
    """Every run in one conversation, oldest first.

    An empty list for a conversation that is not theirs, same as one with no runs yet. The
    distinction is the one thing someone walking ids would want, and no page needs it.
    """
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
async def pin_conversation(
    conversation_id: int, body: PinRequest, user: Annotated[Principal, Depends(current_user)]
) -> Response:
    """Pin or unpin a conversation. 404 for "not yours" as well, same as the delete."""
    if not await domain.pin_conversation(user.id, conversation_id, body.pinned):
        raise HTTPException(status_code=404, detail="no such conversation")
    return Response(status_code=204)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: int, user: Annotated[Principal, Depends(current_user)]
) -> Response:
    """Forget a conversation. The turns under it go too, by cascade.

    404 covers both "no such conversation" and "not yours": the difference is the one thing
    someone probing ids would want to learn.
    """
    if not await domain.forget_conversation(user.id, conversation_id):
        raise HTTPException(status_code=404, detail="no such conversation")
    return Response(status_code=204)
