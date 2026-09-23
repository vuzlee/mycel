"""Ask something, and come back for the answer.

Batch 003 ran the orchestrator inside the request and returned its output. That proved an
HTTP request could reach the agent layer with its trace intact, and it was known to be
wrong for production: a run takes minutes, and every proxy in front of this times out long
before one finishes.

So this is two endpoints rather than one:

    POST /chat          queue a question, return 202 and a job id. Milliseconds.
    GET  /chat/{id}     what happened to it: running, done with an answer, or failed.

**202, not 200.** The status code is the contract: the server accepted the work and has not
done it. A caller that treats 202 as "here is your answer" fails on the empty body rather
than silently reading a half-answer.

The path said `/reports` until batch 033. That was the name from when the app had a button
per capability; the orchestrator has routed a question to whichever specialist covers it
since 026, and there has been one chat box since 027.

Redis answers the poll while a run is in flight, and `app.turn` answers it afterwards. The
TTL that used to make a job id good for an hour stopped mattering in batch 012: the run is
written to both, so the fallback is a row, not a 404.
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from mycel.api.dependencies import current_user
from mycel.core.logging import get_logger
from mycel.domains.chat import ThreadNotFound, find_turn, request_chat
from mycel.infra.redis import results
from mycel.services.auth import Principal

router = APIRouter(prefix="/chat", tags=["chat"])

log = get_logger(__name__)


class ChatRequest(BaseModel):
    """What a caller asks for.

    Without `conversation_id` this is a first question and opens a thread. With one it is
    a follow-up, and the earlier turns of that thread go to the agent with it.
    """

    question: str = Field(min_length=1, max_length=4000, description="What to find out.")
    conversation_id: int | None = Field(
        default=None, description="Continue this thread instead of opening a new one."
    )


class AcceptedResponse(BaseModel):
    """The receipt for queued work. Deliberately not an answer.

    `conversation_id` comes back so the caller can ask the next question into the same
    thread without first looking the thread up by the job id it just received.
    """

    job_id: str
    conversation_id: int
    status: Literal["accepted"] = "accepted"


class ChatResponse(BaseModel):
    """A job's state, and what it produced once there is something.

    `answer` is markdown. It was a union of two schemas until batch 033, when the
    orchestrator stopped filling one: a chatbot picks the shape its answer deserves — a
    table where the data has columns, a sentence where it does not — and a schema had to
    pick for it.

    `spent_usd` is a string rather than a float: money is `Decimal` everywhere else in this
    codebase, and serialising it through a float is how that care gets undone at the last
    step.

    `conversation_id` and `question` describe the run itself, not the thread it sits in.
    A page that read them off the thread would caption every turn with the first question
    asked, and would lose the thread entirely for a link naming a middle run.
    """

    job_id: str
    status: Literal["running", "done", "failed"]
    answer: str | None = None
    spent_usd: str | None = None
    error: str | None = None
    conversation_id: int | None = None
    question: str | None = None


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedResponse)
async def create_chat(
    body: ChatRequest,
    user: Annotated[Principal, Depends(current_user)],
) -> AcceptedResponse:
    """Queue a question and hand back the id to poll with.

    No `MycelDeps` and no budget here: the run happens in the worker, so the ceiling it
    bills against is the worker's (`job_ceiling_usd`), not the API's.

    A thread that is not this caller's reads as 404, not 403: `ThreadNotFound` is one
    exception for both cases so that a caller cannot learn which it was.
    """
    try:
        job_id, thread_id = await request_chat(user.id, body.question, body.conversation_id)
    except ThreadNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no conversation {missing.args[0]}",
        ) from missing
    log.info("chat queued", extra={"job_id": job_id, "conversation_id": thread_id})
    return AcceptedResponse(job_id=job_id, conversation_id=thread_id)


@router.get("/{job_id}", response_model=ChatResponse)
async def get_chat(
    job_id: str,
    user: Annotated[Principal, Depends(current_user)],
) -> ChatResponse:
    """Read what became of a job.

    Redis first, because it is the only one of the two that knows a run is still going.
    Past its TTL the row in `app.turn` answers instead, which is why an answer opened
    tomorrow is an answer and not a 404.

    A run still queued when Redis dropped it reads as `failed` rather than `running`: the
    row says `queued`, and a caller told `running` would poll a job nobody will finish.

    The row is read either way, because `conversation_id` and `question` are only there.
    `request_chat` writes it at queue time in the same transaction as the enqueue, so it
    exists from before a worker picks the job up — the two fields are available for the
    whole life of a run, not only once one has finished.
    """
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
            "status": "done" if kept.status == "done" else "failed",
            "answer": kept.answer,
            "spent_usd": str(kept.spent_usd) if kept.spent_usd is not None else None,
            "error": kept.error,
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no job {job_id}: no such run",
        )

    return ChatResponse(
        job_id=job_id,
        conversation_id=kept.conversation_id if kept else None,
        question=kept.question if kept else None,
        **state,
    )
