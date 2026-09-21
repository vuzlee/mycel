"""The report domain: ask for something, and let a worker build it.

Two kinds of work land here, and they are queued the same way and recorded the same way:

    report     a question for the orchestrator, which searches to answer it
    summary    one project's progress over one window, read out of gold

The work is split across two processes, and the split is visible in the two halves of
this module. `request_*` returns as soon as the job is queued, because either kind takes
minutes; `run` is what the worker calls when it picks the job up.

**The worker calls this, not an agent.** Before batch 013 `queue/consumer.py` built and ran
the orchestrator itself, which put the order of steps in the transport layer — so a second
kind of job meant a second copy of it. The consumer now receives, dispatches here, and
acks; what a job *means* is this module's business.

Every run is written twice: to Redis so a poller can see it finish, and to `app.report` so
it is still there next week. `infra/redis/results.py` calls itself a holding area rather
than a record, and this is where the record is kept.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from mycel.agents.agent.orchestrator import Orchestrator
from mycel.agents.agent.summariser import Summariser
from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.registry import build_deps
from mycel.agents.schemas import ProgressSummary
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.app import AppRepository, ReportRow
from mycel.infra.postgres.session import session_scope
from mycel.infra.redis import budgets, results
from mycel.infra.redis.streams import RedisEventChannel
from mycel.notify.calendar import publish_due_dates
from mycel.notify.telegram import notify_summary
from mycel.queue.job import Job, JobKind
from mycel.services.analyze import summarise_progress
from mycel.services.enqueue import enqueue_report, enqueue_summary
from mycel.services.gather import ProgressWindow, gather_progress

log = get_logger(__name__)

#: The window a summary covers when the caller does not say. Same default as the
#: dashboard's, and for the same reason: a week survives a weekend.
DEFAULT_DAYS = 7

#: How much of a question becomes the thread's title in the sidebar.
TITLE_CHARS = 80


async def request_report(user_id: int, question: str) -> str:
    """Open a thread for a question and queue the work. Returns the job id."""
    async with session_scope() as session:
        repo = AppRepository(session)
        thread = await repo.create_conversation(user_id, kind="chat", title=question[:TITLE_CHARS])
        job_id = await enqueue_report(question, thread.id)
        await repo.upsert_report(thread.id, job_id, question, status="queued")
    return job_id


async def request_summary(user_id: int, project: str, days: int = DEFAULT_DAYS) -> str:
    """Open a thread for one project's progress and queue the work. Returns the job id."""
    title = f"Progress · {project} · {days}d"
    async with session_scope() as session:
        repo = AppRepository(session)
        thread = await repo.create_conversation(user_id, kind="report", title=title)
        job_id = await enqueue_summary(project, days, thread.id)
        await repo.upsert_report(thread.id, job_id, title, status="queued")
    return job_id


async def find_report(job_id: str) -> ReportRow | None:
    """The kept record of a run, whatever Redis has since forgotten.

    This is the half of "written twice" that outlives a TTL, and the reason a report
    opened next week opens rather than 404s.
    """
    async with session_scope() as session:
        return await AppRepository(session).report_by_job_id(job_id)


async def run(job: Job) -> None:
    """Do the work a job asks for, and record what came back.

    Raises on anything that goes wrong: the consumer owns the retry decision, and a domain
    that swallowed the failure would take that decision away from it.
    """
    if job.kind is JobKind.REPORT:
        await _run_report(job)
    elif job.kind is JobKind.SUMMARY:
        await _run_summary(job)
    else:
        raise ValueError(f"no handler for job kind {job.kind!r}")


async def record_failure(job: Job, error: str) -> None:
    """Mark a job as not coming back, in both places it is written."""
    await results.store_failure(job.job_id, error)
    await _record(job, status="failed", error=error[:500])


async def _run_report(job: Job) -> None:
    """A question for the orchestrator."""
    question = str(job.payload.get("question", "")).strip()
    if not question:
        raise ValueError("report job has no question")

    settings = AgentSettings.from_config(Orchestrator.name)
    deps = await _deps(job, settings)
    _log_start(job, settings, deps)
    try:
        report = await runner.run(Orchestrator.build(settings), question, deps)
    finally:
        await budgets.save(deps.budget)

    await _finish(job, report, question, deps.budget.spent_usd)
    log.info(
        "job finished",
        extra={
            "job_id": job.job_id,
            "findings": len(report.findings),
            "gaps": len(report.gaps),
            "spent_usd": str(deps.budget.spent_usd),
        },
    )


async def _run_summary(job: Job) -> None:
    """One project's progress, read out of gold and handed to the summariser.

    The window is queried here and passed whole, not exposed as a tool the agent may call:
    see `services/gather.py` for why one prompt beats a round-trip per question.
    """
    project = str(job.payload.get("project", "")).strip()
    if not project:
        raise ValueError("summary job has no project")
    days = int(str(job.payload.get("days", DEFAULT_DAYS)))

    until = datetime.now(UTC)
    async with session_scope() as session:
        window = await gather_progress(session, project, until - timedelta(days=days), until)

    settings = AgentSettings.from_config(Summariser.name)
    deps = await _deps(job, settings)
    _log_start(job, settings, deps)
    try:
        summary = await summarise_progress(window, deps, settings)
    finally:
        await budgets.save(deps.budget)

    question = f"Progress summary for {project}, last {days} days"
    await _finish(job, summary, question, deps.budget.spent_usd)
    await _send(job, project, summary, window)
    log.info(
        "job finished",
        extra={
            "job_id": job.job_id,
            "items": len(window.items),
            "at_risk": len(summary.at_risk),
            "spent_usd": str(deps.budget.spent_usd),
        },
    )


async def _send(job: Job, project: str, summary: ProgressSummary, window: ProgressWindow) -> None:
    """The two one-way outputs, after the run is recorded and never before.

    Both are optional and neither can fail the job: `notify/` logs its own failures and
    raises nothing, and a report that was produced and written twice is not lost because
    a chat was unreachable or a calendar refused a token.
    """
    await notify_summary(job.job_id, project, summary)
    await publish_due_dates([item for item in window.items if item.due_at])


async def _deps(job: Job, settings: AgentSettings) -> MycelDeps:
    """What one attempt runs with.

    The budget is seeded from Redis rather than from zero: this runs once per *attempt*,
    and a fresh ceiling each time would let one job spend it three times over, silently.
    """
    ceiling = get_settings().job_ceiling_usd
    return build_deps(
        job.job_id,
        ceiling_usd=ceiling,
        settings=settings,
        budget=await budgets.load(job.job_id, ceiling),
        events=RedisEventChannel(job.job_id),
    )


async def _finish(job: Job, body: BaseModel, question: str, spent: Decimal) -> None:
    """Write a finished run to both stores: Redis to be polled, Postgres to be kept."""
    await results.store(job.job_id, body, str(spent))
    await _record(
        job,
        status="done",
        question=question,
        body=body.model_dump(mode="json"),
        spent_usd=spent,
    )


async def _record(
    job: Job,
    status: str,
    question: str | None = None,
    body: dict[str, Any] | None = None,
    error: str | None = None,
    spent_usd: Decimal | None = None,
) -> None:
    """Update the durable row this job already has.

    A missing `conversation_id` is not worth failing a finished run over — the report was
    produced, and Redis has it. It is logged instead, because it means a caller queued a
    job without opening a thread for it.
    """
    conversation_id = int(str(job.payload.get("conversation_id", 0)))
    if not conversation_id:
        log.warning("job has no conversation to record against", extra={"job_id": job.job_id})
        return
    async with session_scope() as session:
        await AppRepository(session).upsert_report(
            conversation_id,
            job.job_id,
            question or str(job.payload.get("question", "")),
            status=status,
            body=body,
            error=error,
            spent_usd=spent_usd,
        )


def _log_start(job: Job, settings: AgentSettings, deps: MycelDeps) -> None:
    log.info(
        "job started",
        extra={
            "job_id": job.job_id,
            "kind": str(job.kind),
            "model": settings.model_spec,
            "spent_usd": str(deps.budget.spent_usd),
        },
    )
