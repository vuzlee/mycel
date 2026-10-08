"""Ask something, and come back for the answer."""

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from mycel.agents.core.chips import Chip
from mycel.api.dependencies import CurrentUser
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.domains.chat import ConversationNotFound, find_turn, request_chat
from mycel.infra.postgres.repositories.conversations import TurnRow
from mycel.infra.redis import citations, results

router = APIRouter(prefix="/chat", tags=["chat"])

log = get_logger(__name__)


class ChatRequest(BaseModel):
    """What a caller asks for."""

    question: str = Field(min_length=1, max_length=4000, description="What to find out.")
    conversation_id: int | None = Field(
        default=None, description="Continue this conversation instead of opening a new one."
    )
    chips: list[Chip] | None = Field(
        default=None,
        description="Sources for this turn; empty means no tools, absent means every tool.",
    )


class AcceptedResponse(BaseModel):
    """The receipt for queued work. Deliberately not an answer."""

    job_id: str
    conversation_id: int
    status: Literal["accepted"] = "accepted"


class ChatResponse(BaseModel):
    """A job's state, and what it produced once there is something."""

    job_id: str
    status: Literal["running", "done", "failed"]
    answer: str | None = None
    spent_usd: str | None = None
    error: str | None = None
    conversation_id: int | None = None
    question: str | None = None
    #: The passages a Knowledge answer cites, so the page can open them.
    sources: list[dict[str, Any]] = []


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedResponse)
async def create_chat(
    body: ChatRequest,
    user: CurrentUser,
) -> AcceptedResponse:
    """Queue a question and hand back the id to poll with."""
    try:
        job_id, conversation_id = await request_chat(
            user.id,
            body.question,
            body.conversation_id,
            chips=[str(c) for c in body.chips] if body.chips is not None else None,
        )
    except ConversationNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no conversation {missing.args[0]}",
        ) from missing
    log.info("chat queued", extra={"job_id": job_id, "conversation_id": conversation_id})
    return AcceptedResponse(job_id=job_id, conversation_id=conversation_id)


def _state_of(kept: TurnRow) -> Literal["running", "done", "failed"]:
    """What a kept row means when Redis has nothing to say about the job."""
    if kept.status == "done":
        return "done"
    if kept.status != "queued":
        return "failed"
    age = datetime.now(UTC) - kept.created_at
    return "running" if age.total_seconds() < get_settings().result_ttl_seconds else "failed"


@router.get("/{job_id}", response_model=ChatResponse)
async def get_chat(
    job_id: str,
    user: CurrentUser,
) -> ChatResponse:
    """Read what became of a job."""
    kept = await find_turn(job_id)
    result = await results.fetch(job_id)

    if result is not None:
        state: dict[str, Any] = {
            "status": result.status,
            "answer": result.answer,
            "spent_usd": result.spent_usd,
            "error": result.error,
        }
    elif kept is not None:
        state = {
            "status": _state_of(kept),
            "answer": kept.answer,
            "spent_usd": str(kept.spent_usd) if kept.spent_usd is not None else None,
            "error": kept.error,
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no job {job_id}: no such run",
        )

    cited = await citations.fetch(job_id)
    sources = cited["sources"] if cited and cited.get("user_id") == user.id else []
    return ChatResponse(
        job_id=job_id,
        conversation_id=kept.conversation_id if kept else None,
        question=kept.question if kept else None,
        sources=sources,
        **state,
    )
