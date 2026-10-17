"""The chat domain: ask something, and let a worker answer it."""

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError

from mycel.agents.core import charts, runner
from mycel.agents.core.chips import parse as parse_chips
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.model_source import ModelSource
from mycel.agents.registry import build_deps
from mycel.agents.specialists.orchestrator import Orchestrator
from mycel.core.chips import Chip
from mycel.core.config import get_settings, zone_of
from mycel.core.logging import get_logger
from mycel.core.principal import Principal
from mycel.core.usage import TurnUsage
from mycel.domains import chat_cache
from mycel.domains.chat_knowledge import (
    answer_without_model,
    cache_writer,
    cite,
    search_query,
)
from mycel.domains.chat_model import model_source
from mycel.events.channel import EventChannel, RecordingChannel
from mycel.events.event import ATTEMPT_STARTED, CHART, NOTICE, AgentEvent
from mycel.infra.postgres.repositories.conversations import (
    ConversationRepository,
)
from mycel.infra.postgres.repositories.identity import IdentityRepository
from mycel.infra.postgres.session import session_scope
from mycel.infra.redis import answers, budgets, citations, claims, results
from mycel.infra.redis.streams import RedisEventChannel
from mycel.observability.metrics import jobs_total
from mycel.observability.turns import chat_turn, observe
from mycel.queue.job import Job
from mycel.services import knowledge, models
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
    #: The model that answers, as a `model_ref`.
    model_ref: str = ""
    #: Set when the asked model could not be used and the default answered instead.
    notice: str | None = None
    #: The answer as stored, citations resolved: what the trace shows as the turn's output.
    answer: str = ""
    #: When this attempt started, for the run time under the answer.
    started: float = field(default_factory=time.monotonic)

    def usage(self) -> TurnUsage:
        budget = self.deps.budget
        return TurnUsage(
            model_ref=self.model_ref,
            tokens_in=budget.tokens_in,
            tokens_out=budget.tokens_out,
            duration_ms=round((time.monotonic() - self.started) * 1000),
        )


async def run(job: Job) -> None:
    """Answer the job's question and record it. Raises; the consumer decides on retry."""
    turn = await _prepare(job)
    if turn is None:
        return
    async with claims.holding(job.job_id):
        with chat_turn(
            question=turn.question,
            conversation_id=int(str(job.payload.get("conversation_id", 0))),
            user_id=turn.principal.id,
            tags=sorted(str(c) for c in turn.chips or ()),
            job_id=job.job_id,
            content=get_settings().otel_capture_content,
        ) as trace:
            await turn.recorder.publish(AgentEvent(agent=Orchestrator.name, type=ATTEMPT_STARTED))
            if turn.notice:
                await turn.recorder.publish(
                    AgentEvent(agent=Orchestrator.name, type=NOTICE, payload={"text": turn.notice})
                )
            if await _ground(turn) or await _replay(turn):
                trace.output(turn.answer)
                return
            answer = await _ask(turn)
            await _settle(turn, answer)
            trace.output(turn.answer)


async def _prepare(job: Job) -> "_Turn | None":
    """Who asked, with which sources and budget; `None` when the job is already answered."""
    question = str(job.payload.get("question", "")).strip()
    if not question:
        raise ValueError("chat job has no question")
    done = await find_turn(job.job_id)
    if done is not None and done.status == "done":
        # Delivered again: the consumer has just said `running`, so say `done` again.
        await results.store(job.job_id, done.answer or "", str(done.spent_usd or 0))
        log.info("chat job already answered", extra={"job_id": job.job_id})
        return None
    principal = await _who_asked(job)
    chips = parse_chips(job.payload.get("chips"))
    asked = job.payload.get("model_ref")
    model_ref, notice = await models.resolve(
        principal.id, asked if isinstance(asked, str) else None
    )
    settings = AgentSettings.from_config(Orchestrator.name)
    model = await model_source(principal.id, model_ref)
    recorder = RecordingChannel(RedisEventChannel(job.job_id))
    return _Turn(
        job=job,
        question=question,
        history=str(job.payload.get("history", "")).strip(),
        principal=principal,
        chips=chips,
        settings=settings,
        recorder=recorder,
        deps=await _deps(job, settings, recorder, principal, chips, model),
        model_ref=model_ref,
        notice=notice,
    )


async def _ground(turn: _Turn) -> bool:
    """Knowledge only: find passages; True when they settle the turn without a model."""
    if turn.chips is None or Chip.KNOWLEDGE not in turn.chips:
        return False
    query = await search_query(turn.job, turn.question, turn.deps)
    content = get_settings().otel_capture_content
    with observe("retrieve-passages", "retriever", input=query, content=content) as step:
        turn.found = await knowledge.retrieve(turn.principal.id, query)
        step.output([c.text for c in turn.found.labelled.values()])
        step.metadata(passages=len(turn.found.labelled), busy=turn.found.busy)
    settled = await answer_without_model(turn.principal.id, turn.chips, turn.found, turn.model_ref)
    if settled is None:
        return False
    text, sources = settled
    await citations.store(turn.job.job_id, turn.principal.id, sources)
    turn.answer = text
    await _finish(turn.job, text, turn.question, Decimal("0"), [], sources, turn.usage())
    await budgets.save(turn.deps.budget)
    return True


async def _replay(turn: _Turn) -> bool:
    """A first question on work data asked before, on data not synced since: no model."""
    if turn.history or (version := await chat_cache.version(turn.chips)) is None:
        return False
    cached = await answers.get(
        turn.principal.id, version, chat_cache.writer(turn.model_ref), turn.question
    )
    if cached is None:
        return False
    turn.answer = cached["answer"]
    shown = list(cached.get("charts", []))
    for step in shown:
        await turn.recorder.publish(
            AgentEvent(agent=step["agent"], type=CHART, payload=step["payload"])
        )
    await _finish(turn.job, turn.answer, turn.question, Decimal("0"), shown, [], turn.usage())
    log.info("chat answered from cache", extra={"job_id": turn.job.job_id})
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
    # A chart the model wrote stays only if every value it plots came back from a tool.
    drawn = any(s.get("type") == CHART for s in turn.recorder.steps)
    answer = charts.settle(answer, getattr(turn.deps, "seen", set()), drawn)
    sources: list[dict[str, Any]] = []
    if found is not None:
        answer, sources = cite(job, answer, found)
        if turn.chips == frozenset({Chip.KNOWLEDGE}):
            await answers.put(
                turn.principal.id,
                found.version,
                cache_writer(turn.model_ref),
                found.query,
                {"answer": answer, "sources": sources},
            )
    elif not turn.history and chat_cache.keepable(turn.recorder.steps):
        if (version := await chat_cache.version(turn.chips)) is not None:
            await answers.put(
                turn.principal.id,
                version,
                chat_cache.writer(turn.model_ref),
                turn.question,
                {
                    "answer": answer,
                    "charts": [s for s in turn.recorder.steps if s.get("type") == CHART],
                },
            )
    spent = turn.deps.budget.spent_usd
    await citations.store(job.job_id, turn.principal.id, sources)
    turn.answer = answer
    await _finish(job, answer, turn.question, spent, turn.recorder.steps, sources, turn.usage())
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
    model: ModelSource | None = None,
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
        model=model,
        tz=zone_of(job.payload.get("timezone")),
    )


async def _finish(
    job: Job,
    answer: str,
    question: str,
    spent: Decimal,
    steps: list[dict[str, Any]],
    sources: list[dict[str, Any]] | None = None,
    usage: TurnUsage | None = None,
) -> None:
    """Write a finished run to both stores: Redis to be polled, Postgres to be kept."""
    await results.store(job.job_id, answer, str(spent), usage)
    await _record(
        job,
        status="done",
        question=question,
        answer=knowledge.with_sources(answer, sources or []),
        spent_usd=spent,
        steps=steps or None,
        usage=usage,
    )


async def _record(
    job: Job,
    status: str,
    question: str | None = None,
    answer: str | None = None,
    error: str | None = None,
    spent_usd: Decimal | None = None,
    steps: list[dict[str, Any]] | None = None,
    usage: TurnUsage | None = None,
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
                usage=usage,
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
            "model": runner.source_of(deps, settings).name,
            "spent_usd": str(deps.budget.spent_usd),
        },
    )
