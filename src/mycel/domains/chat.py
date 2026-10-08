"""The chat domain: ask something, and let a worker answer it.

One kind of work lands here — a question for the orchestrator, which routes it to whichever
specialist covers it and writes up what comes back. The summariser has no endpoint of its
own; the orchestrator reaches it as a tool.

The work is split across two processes, and the split is visible in the two halves of this
module. `request_chat` returns as soon as the job is queued, because a run takes minutes;
`run` is what the worker calls when it picks the job up.

**The worker calls this, not an agent.** Building the orchestrator in `queue/consumer.py`
would put the order of steps in the transport layer. The consumer receives, dispatches
here, and acks; what a job *means* is this module's business.

Every run is written twice: to Redis so a poller can see it finish, and to `app.turn` so it
is still there next week. `infra/redis/results.py` calls itself a holding area rather than
a record, and this is where the record is kept.
"""

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
from mycel.domains import knowledge
from mycel.events.channel import EventChannel, NullChannel, RecordingChannel
from mycel.infra.postgres.repositories.conversations import (
    ConversationRepository,
    ConversationRow,
    TurnRow,
)
from mycel.infra.postgres.repositories.identity import IdentityRepository
from mycel.infra.postgres.session import session_scope
from mycel.infra.redis import answers, budgets, citations, results
from mycel.infra.redis.streams import RedisEventChannel
from mycel.observability.metrics import jobs_total
from mycel.queue.job import Job
from mycel.services.auth import Principal
from mycel.services.citations import check
from mycel.services.enqueue import enqueue_chat

log = get_logger(__name__)

#: How much of a question becomes the conversation's title in the sidebar.
TITLE_CHARS = 80

#: How many earlier turns a follow-up carries. A follow-up leans on what was just said,
#: not on the first thing asked, and every turn is paid for in tokens on every turn after
#: it.
HISTORY_TURNS = 6

#: And a ceiling in characters, because one long answer outweighs six short turns. Counting
#: turns alone does not bound anything.
HISTORY_CHARS = 6000

#: What the rewriter reads for a follow-up's search: "it" points at something recent.
REWRITE_QUESTIONS = 3
REWRITE_ANSWER_CHARS = 500


class ConversationNotFound(Exception):
    """The conversation asked for is not this person's, or not there.

    One exception for both, on purpose: telling a caller a conversation exists but belongs to
    someone else tells them something they did not have.
    """


async def request_chat(
    user_id: int,
    question: str,
    conversation_id: int | None = None,
    chips: list[str] | None = None,
) -> tuple[str, int]:
    """Queue a question; returns the job id and its conversation (new if none is given)."""
    async with session_scope() as session:
        repo = ConversationRepository(session)
        if conversation_id is None:
            conversation = await repo.create_conversation(
                user_id, kind="chat", title=question[:TITLE_CHARS]
            )
            turns = []
        else:
            conversation = await _conversation_of(repo, user_id, conversation_id)
            turns = await repo.turns_for_conversation(conversation.id)

        previous = context = ""
        if chips is not None and Chip.KNOWLEDGE in chips:
            previous, context = _last_question(turns), _rewrite_context(turns)
        job_id = await enqueue_chat(
            question,
            conversation.id,
            _recall(turns),
            user_id=user_id,
            chips=chips,
            previous=previous,
            context=context,
        )
        await repo.upsert_turn(conversation.id, job_id, question, status="queued")
    return job_id, conversation.id


def _last_question(turns: list[TurnRow]) -> str:
    """The question before this one, for a follow-up's search. Empty on a first question."""
    return turns[-1].question if turns else ""


def _rewrite_context(turns: list[TurnRow]) -> str:
    """What the rewriter reads: the last few questions and the head of the last answer."""
    if not turns:
        return ""
    asked = "\n".join(f"- {t.question}" for t in turns[-REWRITE_QUESTIONS:])
    said = [t.answer for t in turns if t.status == "done" and t.answer]
    text = f"Earlier questions:\n{asked}"
    if said:
        text += f"\n\nStart of the last answer:\n{said[-1][:REWRITE_ANSWER_CHARS]}"
    return text


async def _conversation_of(
    repo: ConversationRepository, user_id: int, conversation_id: int
) -> ConversationRow:
    """The conversation a follow-up names, once it is established that it is this person's."""
    conversation = await repo.conversation_by_id(conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise ConversationNotFound(conversation_id)
    return conversation


def _recall(turns: list[TurnRow]) -> str:
    """Earlier turns of a conversation, as text for the prompt.

    Text rather than `message_history`: the cap and the "omitted" line below are Mycel's
    decisions, and handing the framework a message list would give it the trimming.

    Only finished turns. A failed one has nothing to remember, and showing a model how a
    run went wrong is not context, it is an example to follow.
    """
    done = [turn for turn in turns if turn.status == "done" and turn.answer]
    if not done:
        return ""

    kept: list[str] = []
    spent = 0
    # Newest first, so the ceiling drops the oldest turns rather than the ones a follow-up
    # is actually about.
    for turn in reversed(done[-HISTORY_TURNS:]):
        block = f"Q: {turn.question}\nA: {turn.answer}"
        if kept and spent + len(block) > HISTORY_CHARS:
            break
        kept.append(block)
        spent += len(block)

    kept.reverse()
    dropped = len(done) - len(kept)
    head = "Earlier in this conversation"
    if dropped:
        head += f" ({dropped} earlier turn(s) omitted)"
    return f"{head}:\n\n" + "\n\n".join(kept)


async def find_turn(job_id: str) -> TurnRow | None:
    """The kept record of a run, whatever Redis has since forgotten.

    This is the half of "written twice" that outlives a TTL, and the reason an answer
    opened next week opens rather than 404s.
    """
    async with session_scope() as session:
        return await ConversationRepository(session).turn_by_job_id(job_id)


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
    """Write a finished run to both stores: Redis to be polled, Postgres to be kept.

    The steps go with the answer and only with it. A failed run leaves half a chain of
    tool calls, which is something to read in the logs, not something a conversation should
    replay as if it were work done.
    """
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
    """Update the durable row this job already has, if it still has one.

    A missing `conversation_id` is not worth failing a finished run over — the answer was
    produced, and Redis has it. It is logged instead, because it means a caller queued a
    job without opening a conversation for it.

    Neither is a conversation deleted while the job ran. The row this job wrote at queue time
    went with it (`ON DELETE CASCADE`), so the upsert finds nothing to update and inserts,
    and the insert fails the foreign key. There is nowhere left to keep the run and nobody
    left to read it: the conversation is gone from the rail and from `/conversations`.

    Swallowed here rather than left to the consumer, because the consumer's last resort is
    to call `record_failure`, which lands in this same function against the same missing
    conversation — so the failure path raises too, the message is never acked, and one deleted
    conversation leaves a job unacked until the broker's `consumer_timeout` redelivers it to fail
    the same way again.
    """
    # Counted here rather than at each call site: this is the one function both the done
    # and the failed path go through, and it already has the word for which one it was.
    # Before the early return, because a job with no conversation still ended.
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
