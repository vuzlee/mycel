"""The chat domain: ask something, and let a worker answer it."""

from dataclasses import replace
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError

from mycel.agents.agent.orchestrator import Orchestrator
from mycel.agents.agent.rewriter import Rewriter
from mycel.agents.core import runner
from mycel.agents.core.chips import Chip
from mycel.agents.core.chips import parse as parse_chips
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.registry import build_deps
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.events.channel import EventChannel, NullChannel, RecordingChannel
from mycel.infra.postgres.repositories.conversations import (
    ConversationRepository,
)
from mycel.infra.postgres.repositories.identity import IdentityRepository
from mycel.infra.postgres.session import session_scope
from mycel.infra.redis import answers, budgets, citations, results
from mycel.infra.redis.streams import RedisEventChannel
from mycel.observability.metrics import jobs_total
from mycel.queue.job import Job
from mycel.services import knowledge
from mycel.services.auth import Principal
from mycel.services.chat import find_turn
from mycel.services.citations import check

log = get_logger(__name__)


async def run(job: Job) -> None:
    """Answer the job's question and record it. Raises; the consumer decides on retry."""
    question = str(job.payload.get("question", "")).strip()
    if not question:
        raise ValueError("chat job has no question")
    done = await find_turn(job.job_id)
    if done is not None and done.status == "done":
        log.info("chat job already answered", extra={"job_id": job.job_id})
        return
    history = str(job.payload.get("history", "")).strip()
    principal = await _who_asked(job)
    chips = parse_chips(job.payload.get("chips"))

    settings = AgentSettings.from_config(Orchestrator.name)
    recorder = RecordingChannel(RedisEventChannel(job.job_id))
    deps = await _deps(job, settings, recorder, principal, chips)

    found: knowledge.Retrieved | None = None
    if chips is not None and Chip.KNOWLEDGE in chips:
        query = await _search_query(job, question, deps)
        found = await knowledge.retrieve(principal.id, query)
        if await _answer_without_model(job, question, principal.id, chips, found):
            await budgets.save(deps.budget)
            return

    prompt = f"{history}\n\nThe question now:\n{question}" if history else question
    if found is not None and found.labelled:
        prompt = f"{knowledge.render(found.labelled)}\n\n{prompt}"

    _log_start(job, settings, deps)
    try:
        answer = await runner.run(Orchestrator.build(settings), prompt, deps)
    finally:
        await budgets.save(deps.budget)

    if recorder.dropped:
        log.warning(
            "tool calls past the ceiling were not kept",
            extra={"job_id": job.job_id, "dropped": recorder.dropped},
        )
    sources: list[dict[str, Any]] = []
    if found is not None:
        answer, sources = _cite(job, answer, found)
        if chips == frozenset({Chip.KNOWLEDGE}):
            await answers.put(
                principal.id,
                found.version,
                _writer(settings),
                found.query,
                {"answer": answer, "sources": sources},
            )
    await citations.store(job.job_id, principal.id, sources)
    await _finish(job, answer, question, deps.budget.spent_usd, recorder.steps, sources)
    log.info(
        "job finished",
        extra={
            "job_id": job.job_id,
            "chars": len(answer),
            "spent_usd": str(deps.budget.spent_usd),
        },
    )


async def _search_query(job: Job, question: str, deps: MycelDeps) -> str:
    """The follow-up rewritten to stand alone; the stitched text if the rewrite fails."""
    previous = str(job.payload.get("previous", "")).strip()
    context = str(job.payload.get("context", "")).strip()
    stitched = knowledge.search_text(question, previous[: get_settings().ask_max_chars])
    if not context:
        return stitched
    settings = AgentSettings.from_config(Rewriter.name)
    rewrite_deps = replace(deps, settings=settings, events=NullChannel())
    prompt = f"{context}\n\nThe question now:\n{question}"
    try:
        rewritten = await runner.run(Rewriter.build(settings), prompt, rewrite_deps)
    except Exception as exc:
        log.warning("rewrite failed", extra={"job_id": job.job_id, "error": str(exc)})
        return stitched
    rewritten = rewritten.strip()[: get_settings().ask_max_chars]
    return rewritten or stitched


async def _answer_without_model(
    job: Job,
    question: str,
    user_id: int,
    chips: frozenset[Chip],
    found: knowledge.Retrieved,
) -> bool:
    """A Knowledge-only turn the documents settle alone: busy, nothing found, or cached."""
    if chips != frozenset({Chip.KNOWLEDGE}):
        return False
    if found.busy:
        text, sources = knowledge.BUSY, list[dict[str, Any]]()
    elif not found.labelled:
        text, sources = knowledge.NOT_FOUND, []
    else:
        settings = AgentSettings.from_config(Orchestrator.name)
        cached = await answers.get(user_id, found.version, _writer(settings), found.query)
        if cached is None:
            return False
        text, sources = cached["answer"], cached["sources"]
    await citations.store(job.job_id, user_id, sources)
    await _finish(job, text, question, Decimal("0"), [], sources)
    return True


def _writer(settings: AgentSettings) -> str:
    """What a cached Knowledge answer depends on besides the documents: prompt and models."""
    return answers.writer(
        Orchestrator.instructions, (settings.model_spec, *settings.fallback_specs)
    )


def _cite(job: Job, answer: str, found: knowledge.Retrieved) -> tuple[str, list[dict[str, Any]]]:
    """Strip markers for passages not sent; the rest become the turn's sources."""
    checked = check(answer, list(found.labelled))
    if checked.dropped:
        log.warning("citations dropped", extra={"job_id": job.job_id, "dropped": checked.dropped})
    sources = [knowledge.source(label, found.labelled[label]) for label in checked.cited]
    return checked.answer, sources


async def record_failure(job: Job, error: str) -> None:
    """Mark a job as not coming back, in both places it is written."""
    await results.store_failure(job.job_id, error)
    await _record(job, status="failed", error=error[:500])


async def _who_asked(job: Job) -> Principal:
    """The person who queued the job. Raises instead of running as nobody."""
    user_id = job.payload.get("user_id")
    if not isinstance(user_id, int):
        raise ValueError("chat job has no user_id")
    async with session_scope() as session:
        user = await IdentityRepository(session).user_by_id(user_id)
    if user is None:
        raise ValueError(f"chat job belongs to user {user_id}, who no longer exists")
    return Principal(id=user.id, email=user.email)


async def _deps(
    job: Job,
    settings: AgentSettings,
    events: EventChannel,
    principal: Principal,
    chips: frozenset[Chip] | None,
) -> MycelDeps:
    """What one attempt runs with."""
    ceiling = get_settings().job_ceiling_usd
    return build_deps(
        job.job_id,
        ceiling_usd=ceiling,
        settings=settings,
        budget=await budgets.load(job.job_id, ceiling),
        events=events,
        principal=principal,
        chips=chips,
    )


async def _finish(
    job: Job,
    answer: str,
    question: str,
    spent: Decimal,
    steps: list[dict[str, Any]],
    sources: list[dict[str, Any]] | None = None,
) -> None:
    """Write a finished run to both stores: Redis to be polled, Postgres to be kept."""
    await results.store(job.job_id, answer, str(spent))
    await _record(
        job,
        status="done",
        question=question,
        answer=knowledge.with_sources(answer, sources or []),
        spent_usd=spent,
        steps=steps or None,
    )


async def _record(
    job: Job,
    status: str,
    question: str | None = None,
    answer: str | None = None,
    error: str | None = None,
    spent_usd: Decimal | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> None:
    """Update the durable row this job already has, if it still has one."""
    # Counted here: both the done and the failed paths go through this function.
    jobs_total.labels(kind=str(job.kind), status=status).inc()

    conversation_id = int(str(job.payload.get("conversation_id", 0)))
    if not conversation_id:
        log.warning("job has no conversation to record against", extra={"job_id": job.job_id})
        return
    try:
        async with session_scope() as session:
            await ConversationRepository(session).upsert_turn(
                conversation_id,
                job.job_id,
                question or str(job.payload.get("question", "")),
                status=status,
                answer=answer,
                error=error,
                spent_usd=spent_usd,
                steps=steps,
            )
    except IntegrityError:
        log.warning(
            "conversation was deleted while the job ran; nothing to record against",
            extra={"job_id": job.job_id, "conversation_id": conversation_id},
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
