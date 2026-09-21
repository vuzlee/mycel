"""Ask for a report, and come back for it.

Batch 003 ran the orchestrator inside the request and returned the `Report`. That proved
an HTTP request could reach the agent layer with its trace intact, and it was known to be
wrong for production: a report takes minutes, and every proxy in front of this times out
long before one finishes.

So this is now two endpoints rather than one:

    POST /reports          queue a question, return 202 and a job id. Milliseconds.
    POST /reports/summary  queue one project's progress over one window. Same receipt.
    GET  /reports/{id}     what happened to it: running, done with a body, or failed.

**202, not 200.** The status code is the contract: the server accepted the work and has
not done it. A caller that treats 202 as "here is your report" fails on the empty body
rather than silently reading a half-answer.

Redis answers the poll while a run is in flight, and `app.report` answers it afterwards.
The TTL that used to make a job id good for an hour stopped mattering in batch 012: the
run is written to both, so the fallback is a row, not a 404.
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, TypeAdapter

from mycel.agents.schemas import ProgressSummary, Report
from mycel.api.dependencies import current_user
from mycel.core.logging import get_logger
from mycel.domains.dashboard import DEFAULT_DAYS
from mycel.domains.report import find_report, request_report, request_summary
from mycel.infra.redis import results
from mycel.services.auth import Principal
from mycel.services.permission import may_read_project

router = APIRouter(prefix="/reports", tags=["reports"])

#: Longest summary window. The same ceiling the dashboard uses, for the same reason: past
#: this it is an export, not a standup.
MAX_DAYS = 90

log = get_logger(__name__)


class ReportRequest(BaseModel):
    """What a caller asks for."""

    question: str = Field(min_length=1, max_length=4000, description="What to find out.")


class SummaryRequest(BaseModel):
    """Which project, and how far back."""

    project: str = Field(
        min_length=1, max_length=32, description="The project key to summarise, e.g. 'MYC'."
    )
    days: int = Field(default=DEFAULT_DAYS, ge=1, le=MAX_DAYS, description="Window length.")


class AcceptedResponse(BaseModel):
    """The receipt for queued work. Deliberately not a report."""

    job_id: str
    status: Literal["accepted"] = "accepted"


class ReportResponse(BaseModel):
    """A job's state, and what it produced once there is something.

    `report` is a union, not `Report`: this one endpoint is polled for both kinds of job,
    and a summary is not a research report. Left-to-right, so a `Report` never matches as
    a `ProgressSummary` with every field defaulted — the two share no required field, but
    the order makes that independent of how either schema grows.

    `spent_usd` is a string rather than a float: money is `Decimal` everywhere else in
    this codebase, and serialising it through a float is how that care gets undone at the
    last step.
    """

    job_id: str
    status: Literal["running", "done", "failed"]
    report: Report | ProgressSummary | None = None
    spent_usd: str | None = None
    error: str | None = None


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedResponse)
async def create_report(
    body: ReportRequest,
    user: Annotated[Principal, Depends(current_user)],
) -> AcceptedResponse:
    """Queue a report and hand back the id to poll with.

    No `MycelDeps` and no budget here any more: the run happens in the worker, so the
    ceiling it bills against is the worker's (`job_ceiling_usd`), not the API's.
    """
    job_id = await request_report(user.id, body.question)
    log.info("report queued", extra={"job_id": job_id})
    return AcceptedResponse(job_id=job_id)


@router.post("/summary", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedResponse)
async def create_summary(
    body: SummaryRequest,
    user: Annotated[Principal, Depends(current_user)],
) -> AcceptedResponse:
    """Queue a progress summary for one project.

    Declared before `GET /{job_id}` matters not at all — they differ by method — but the
    path does: `/reports/summary` is a literal and would be swallowed by a `POST /{job_id}`
    if one ever existed. There is no such route, and this comment is why there should not
    be one.
    """
    if not await may_read_project(user, body.project):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your project")

    job_id = await request_summary(user.id, body.project, body.days)
    log.info("summary queued", extra={"job_id": job_id, "project": body.project})
    return AcceptedResponse(job_id=job_id)


@router.get("/{job_id}", response_model=ReportResponse)
async def get_report(
    job_id: str,
    user: Annotated[Principal, Depends(current_user)],
) -> ReportResponse:
    """Read what became of a job.

    Redis first, because it is the only one of the two that knows a run is still going.
    Past its TTL the row in `app.report` answers instead, which is why a report opened
    tomorrow is a report and not a 404.

    A run still queued when Redis dropped it reads as `failed` rather than `running`: the
    row says `queued`, and a caller told `running` would poll a job nobody will finish.
    """
    result = await results.fetch(job_id)
    if result is not None:
        return ReportResponse(
            job_id=result.job_id,
            status=result.status,
            report=_body(result.report),
            spent_usd=result.spent_usd,
            error=result.error,
        )

    kept = await find_report(job_id)
    if kept is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no job {job_id}: no such run",
        )

    return ReportResponse(
        job_id=kept.job_id,
        status="done" if kept.status == "done" else "failed",
        report=_body(kept.body),
        spent_usd=str(kept.spent_usd) if kept.spent_usd is not None else None,
        error=kept.error,
    )


def _body(raw: dict[str, Any] | None) -> Report | ProgressSummary | None:
    """Whichever schema the stored body fits.

    A `TypeAdapter` rather than two `try`/`except` blocks: the union is declared once, on
    `ReportResponse`, and this cannot drift out of step with it.
    """
    return _BODY.validate_python(raw) if raw else None


_BODY: TypeAdapter[Report | ProgressSummary] = TypeAdapter(Report | ProgressSummary)
