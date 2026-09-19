"""Ask for a report, and come back for it.

Batch 003 ran the orchestrator inside the request and returned the `Report`. That proved
an HTTP request could reach the agent layer with its trace intact, and it was known to be
wrong for production: a report takes minutes, and every proxy in front of this times out
long before one finishes.

So this is now two endpoints rather than one:

    POST /reports        queue the job, return 202 and a job id. Returns in milliseconds.
    GET  /reports/{id}   what happened to it: running, done with a report, or failed.

**202, not 200.** The status code is the contract: the server accepted the work and has
not done it. A caller that treats 202 as "here is your report" fails on the empty body
rather than silently reading a half-answer.

The result store is Redis with a TTL, not a table — see `storage/redis/results.py` for why that is
deliberate and what it costs. It means a job id is good for an hour, not forever.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from mycel.agents.orchestrator import Report
from mycel.core.logging import get_logger
from mycel.services.enqueue import enqueue_report
from mycel.storage.redis import results

router = APIRouter(prefix="/reports", tags=["reports"])

log = get_logger(__name__)


class ReportRequest(BaseModel):
    """What a caller asks for."""

    question: str = Field(min_length=1, max_length=4000, description="What to find out.")


class AcceptedResponse(BaseModel):
    """The receipt for queued work. Deliberately not a report."""

    job_id: str
    status: Literal["accepted"] = "accepted"


class ReportResponse(BaseModel):
    """A job's state, and its report once there is one.

    `spent_usd` is a string rather than a float: money is `Decimal` everywhere else in
    this codebase, and serialising it through a float is how that care gets undone at the
    last step.
    """

    job_id: str
    status: Literal["running", "done", "failed"]
    report: Report | None = None
    spent_usd: str | None = None
    error: str | None = None


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedResponse)
async def create_report(body: ReportRequest) -> AcceptedResponse:
    """Queue a report and hand back the id to poll with.

    No `MycelDeps` and no budget here any more: the run happens in the worker, so the
    ceiling it bills against is the worker's (`job_ceiling_usd`), not the API's.
    """
    job_id = await enqueue_report(body.question)
    log.info("report queued", extra={"job_id": job_id})
    return AcceptedResponse(job_id=job_id)


@router.get("/{job_id}", response_model=ReportResponse)
async def get_report(job_id: str) -> ReportResponse:
    """Read what became of a job.

    404 covers both "never existed" and "expired past its TTL". They are the same thing to
    a caller — there is nothing to show either way — and telling them apart would need a
    record `storage/redis/results.py` deliberately does not keep.
    """
    result = await results.fetch(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no job {job_id}: it never existed, or its result has expired",
        )

    return ReportResponse(
        job_id=result.job_id,
        status=result.status,
        report=Report.model_validate(result.report) if result.report else None,
        spent_usd=result.spent_usd,
        error=result.error,
    )
