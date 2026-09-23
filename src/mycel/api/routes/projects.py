"""The two lists a page needs before it can ask for anything else.

    GET  /projects       which projects have work in them, for the picker
    GET     /conversations             this person's threads, for the sidebar
    GET     /conversations/{id}/turns  every run in one thread, oldest first
    DELETE  /conversations/{id}        forget one, and every run under it

Both are behind `current_user`: the second is by definition personal, and the first names
the projects this deployment reads, which is not public either.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from mycel.api.dependencies import current_user
from mycel.domains.dashboard import known_projects
from mycel.domains.threads import HISTORY_LIMIT, forget_thread, list_threads, thread_turns
from mycel.services.auth import Principal
from mycel.services.permission import readable_projects

router = APIRouter(tags=["projects"])


class ThreadResponse(BaseModel):
    """One row in the sidebar.

    `job_id` is null for a thread whose run has not produced anything yet. The page shows
    that as a queued run rather than hiding the row — a job the worker never picked up is
    exactly what someone needs to see.
    """

    id: int
    kind: str
    title: str
    created_at: datetime
    job_id: str | None = None
    status: str | None = None


class TurnResponse(BaseModel):
    """One run inside a thread, as the page replays it.

    `answer` comes back whole rather than summarised: it is markdown the page already
    knows how to render, and shortening it here would be a second opinion about the same
    text.
    """

    job_id: str
    question: str
    status: str
    answer: str | None = None
    spent_usd: str | None = None
    error: str | None = None
    created_at: datetime


@router.get("/projects", response_model=list[str])
async def read_projects(user: Annotated[Principal, Depends(current_user)]) -> list[str]:
    """Projects with work in them, filtered to the ones this person may read.

    A list of keys and nothing else. A project has no attributes of its own in gold — its
    counts belong to a window, and asking for a window is what `/dashboard` is for.
    """
    allowed = await readable_projects(user)
    return [key for key in await known_projects() if key in allowed]


@router.get("/conversations", response_model=list[ThreadResponse])
async def read_conversations(
    user: Annotated[Principal, Depends(current_user)],
    limit: int = Query(default=HISTORY_LIMIT, ge=1, le=HISTORY_LIMIT),
) -> list[ThreadResponse]:
    """This person's threads, newest first. The sidebar, and it follows them to any
    browser — which is the whole reason `localStorage` stopped being where it lived."""
    threads = await list_threads(user.id, limit)
    return [
        ThreadResponse(
            id=t.conversation.id,
            kind=t.conversation.kind,
            title=t.conversation.title,
            created_at=t.conversation.created_at,
            job_id=t.job_id,
            status=t.status,
        )
        for t in threads
    ]


@router.get("/conversations/{conversation_id}/turns", response_model=list[TurnResponse])
async def read_turns(
    conversation_id: int, user: Annotated[Principal, Depends(current_user)]
) -> list[TurnResponse]:
    """Every run in one thread, oldest first.

    An empty list for a thread that is not theirs, same as one with no runs yet. The
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
            created_at=turn.created_at,
        )
        for turn in await thread_turns(user.id, conversation_id)
    ]


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: int, user: Annotated[Principal, Depends(current_user)]
) -> Response:
    """Forget a thread. The turns under it go too, by cascade.

    404 covers both "no such thread" and "not yours": the difference is the one thing
    someone probing ids would want to learn.
    """
    if not await forget_thread(user.id, conversation_id):
        raise HTTPException(status_code=404, detail="no such conversation")
    return Response(status_code=204)
