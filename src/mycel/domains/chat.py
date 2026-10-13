"""The chat domain: ask something, and let a worker answer it."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError

from mycel.agents.core import runner
from mycel.agents.core.chips import parse as parse_chips
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.registry import build_deps
from mycel.agents.specialists.orchestrator import Orchestrator
from mycel.core.chips import Chip
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.core.principal import Principal
from mycel.domains.chat_knowledge import (
    answer_without_model,
    cache_writer,
    cite,
    search_query,
)
from mycel.events.channel import EventChannel, RecordingChannel
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
from mycel.services.chat import find_turn

log = get_logger(__name__)


@dataclass
class _Turn:
    """One attempt at one question, as the steps below pass it along."""

    job: Job
    question: str
    history: str
    principal: Principal
    chips: frozenset[Chip] | None
    settings: AgentSettings
    recorder: RecordingChannel
    deps: MycelDeps
    found: knowledge.Retrieved | None = None


async def run(job: Job) -> None:
    """Answer the job's question and record it. Raises; the consumer decides on retry."""
    turn = await _prepare(job)
    if turn is None or await _ground(turn):
        return
    answer = await _ask(turn)
    await _settle(turn, answer)


async def _prepare(job: Job) -> "_Turn | None":
    """Who asked, with which sources and budget; `None` when the job is already answered."""
    question = str(job.payload.get("question", "")).strip()
    if not question:
        raise ValueError("chat job has no question")
    done = await find_turn(job.job_id)
    if done is not None and done.status == "done":
        log.info("chat job already answered", extra={"job_id": job.job_id})
        return None
    principal = await _who_asked(job)
    chips = parse_chips(job.payload.get("chips"))
    settings = AgentSettings.from_config(Orchestrator.name)
    recorder = RecordingChannel(RedisEventChannel(job.job_id))
    return _Turn(
        job=job,
        question=question,
        history=str(job.payload.get("history", "")).strip(),
        principal=principal,
        chips=chips,
        settings=settings,
        recorder=recorder,
        deps=await _deps(job, settings, recorder, principal, chips),
    )


async def _ground(turn: _Turn) -> bool:
    """Knowledge only: find passages; True when they settle the turn without a model."""
    if turn.chips is None or Chip.KNOWLEDGE not in turn.chips:
        return False
    query = await search_query(turn.job, turn.question, turn.deps)
    turn.found = await knowledge.retrieve(turn.principal.id, query)
    settled = await answer_without_model(turn.principal.id, turn.chips, turn.found)
    if settled is None:
        return False
    text, sources = settled
    await citations.store(turn.job.job_id, turn.principal.id, sources)
    await _finish(turn.job, text, turn.question, Decimal("0"), [], sources)
    await budgets.save(turn.deps.budget)
    return True


async def _ask(turn: _Turn) -> str:
    """The orchestrator's answer; what it spent is saved even when it raises."""
    prompt = (
        f"{turn.history}\n\nThe question now:\n{turn.question}" if turn.history else turn.question
    )
    if turn.found is not None and turn.found.labelled:
        prompt = f"{knowledge.render(turn.found.labelled)}\n\n{prompt}"
    _log_start(turn.job, turn.settings, turn.deps)
    try:
        return await runner.run(Orchestrator.build(turn.settings), prompt, turn.deps)
    finally:
        await budgets.save(turn.deps.budget)


async def _settle(turn: _Turn, answer: str) -> None:
    """Cite, cache, and write the finished turn where it is polled and where it is kept."""
    job, found = turn.job, turn.found
    if turn.recorder.dropped:
        log.warning(
            "tool calls past the ceiling were not kept",
            extra={"job_id": job.job_id, "dropped": turn.recorder.dropped},
        )
    sources: list[dict[str, Any]] = []
    if found is not None:
        answer, sources = cite(job, answer, found)
        if turn.chips == frozenset({Chip.KNOWLEDGE}):
            await answers.put(
                turn.principal.id,
                found.version,
                cache_writer(turn.settings),
                found.query,
                {"answer": answer, "sources": sources},
            )
    spent = turn.deps.budget.spent_usd
    await citations.store(job.job_id, turn.principal.id, sources)
    await _finish(job, answer, turn.question, spent, turn.recorder.steps, sources)
    log.info(
        "job finished",
        extra={"job_id": job.job_id, "chars": len(answer), "spent_usd": str(spent)},
    )


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
