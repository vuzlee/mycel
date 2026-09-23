"""The chat domain: ask something, and let a worker answer it.

One kind of work lands here — a question for the orchestrator, which routes it to whichever
specialist covers it and writes up what comes back. Until batch 033 there was a second,
`summary`, with its own endpoint and its own agent; the orchestrator reaches the summariser
as a tool, so the endpoint was a second way to the same capability and went.

The work is split across two processes, and the split is visible in the two halves of this
module. `request_chat` returns as soon as the job is queued, because a run takes minutes;
`run` is what the worker calls when it picks the job up.

**The worker calls this, not an agent.** Before batch 013 `queue/consumer.py` built and ran
the orchestrator itself, which put the order of steps in the transport layer. The consumer
now receives, dispatches here, and acks; what a job *means* is this module's business.

Every run is written twice: to Redis so a poller can see it finish, and to `app.turn` so it
is still there next week. `infra/redis/results.py` calls itself a holding area rather than
a record, and this is where the record is kept.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError

from mycel.agents.agent.orchestrator import Orchestrator
from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.registry import build_deps
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.events.channel import EventChannel, RecordingChannel
from mycel.infra.postgres.repositories.app import AppRepository, ConversationRow, TurnRow
from mycel.infra.postgres.session import session_scope
from mycel.infra.redis import budgets, results
from mycel.infra.redis.streams import RedisEventChannel
from mycel.queue.job import Job
from mycel.services.enqueue import enqueue_chat

log = get_logger(__name__)

#: How much of a question becomes the thread's title in the sidebar.
TITLE_CHARS = 80

#: How many earlier turns a follow-up carries. A follow-up leans on what was just said,
#: not on the first thing asked, and every turn is paid for in tokens on every turn after
#: it.
HISTORY_TURNS = 6

#: And a ceiling in characters, because one long answer outweighs six short turns. Counting
#: turns alone does not bound anything.
HISTORY_CHARS = 6000


class ThreadNotFound(Exception):
    """The conversation asked for is not this person's, or not there.

    One exception for both, on purpose: telling a caller a thread exists but belongs to
    someone else tells them something they did not have.
    """


async def request_chat(
    user_id: int, question: str, conversation_id: int | None = None
) -> tuple[str, int]:
    """Queue a question and return the job id with the thread it landed in.

    With a `conversation_id` the question joins that thread and carries what it has said
    so far; without one it opens a new thread, which is what a first question does.

    The history is read here and travels in the payload rather than being looked up by the
    worker. `idempotency_key` hashes kind plus payload, so the same words asked twice at
    different points in a thread are different work and must hash differently — a worker
    that re-read the history would make the second job a duplicate of the first and drop
    it.
    """
    async with session_scope() as session:
        repo = AppRepository(session)
        if conversation_id is None:
            thread = await repo.create_conversation(
                user_id, kind="chat", title=question[:TITLE_CHARS]
            )
            history = ""
        else:
            thread = await _thread_of(repo, user_id, conversation_id)
            history = _recall(await repo.turns_for_conversation(thread.id))

        job_id = await enqueue_chat(question, thread.id, history)
        await repo.upsert_turn(thread.id, job_id, question, status="queued")
    return job_id, thread.id


async def _thread_of(repo: AppRepository, user_id: int, conversation_id: int) -> ConversationRow:
    """The thread a follow-up names, once it is established that it is this person's."""
    thread = await repo.conversation_by_id(conversation_id)
    if thread is None or thread.user_id != user_id:
        raise ThreadNotFound(conversation_id)
    return thread


def _recall(turns: list[TurnRow]) -> str:
    """Earlier turns of a thread, as text for the prompt.

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
        return await AppRepository(session).turn_by_job_id(job_id)


async def run(job: Job) -> None:
    """Do the work a job asks for, and record what came back.

    Raises on anything that goes wrong: the consumer owns the retry decision, and a domain
    that swallowed the failure would take that decision away from it.

    No dispatch on `job.kind` since batch 033 — there is one kind. The `if` came back every
    time a kind was added and is not worth keeping empty for the next one.
    """
    question = str(job.payload.get("question", "")).strip()
    if not question:
        raise ValueError("chat job has no question")
    history = str(job.payload.get("history", "")).strip()
    prompt = f"{history}\n\nThe question now:\n{question}" if history else question

    settings = AgentSettings.from_config(Orchestrator.name)
    recorder = RecordingChannel(RedisEventChannel(job.job_id))
    deps = await _deps(job, settings, recorder)
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
    await _finish(job, answer, question, deps.budget.spent_usd, recorder.steps)
    log.info(
        "job finished",
        extra={
            "job_id": job.job_id,
            "chars": len(answer),
            "spent_usd": str(deps.budget.spent_usd),
        },
    )


async def record_failure(job: Job, error: str) -> None:
    """Mark a job as not coming back, in both places it is written."""
    await results.store_failure(job.job_id, error)
    await _record(job, status="failed", error=error[:500])


async def _deps(job: Job, settings: AgentSettings, events: EventChannel) -> MycelDeps:
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
    )


async def _finish(
    job: Job, answer: str, question: str, spent: Decimal, steps: list[dict[str, Any]]
) -> None:
    """Write a finished run to both stores: Redis to be polled, Postgres to be kept.

    The steps go with the answer and only with it. A failed run leaves half a chain of
    tool calls, which is something to read in the logs, not something a thread should
    replay as if it were work done.
    """
    await results.store(job.job_id, answer, str(spent))
    await _record(
        job,
        status="done",
        question=question,
        answer=answer,
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
    job without opening a thread for it.

    Neither is a thread deleted while the job ran. The row this job wrote at queue time
    went with it (`ON DELETE CASCADE`), so the upsert finds nothing to update and inserts,
    and the insert fails the foreign key. There is nowhere left to keep the run and nobody
    left to read it: the thread is gone from the rail and from `/conversations`.

    Swallowed here rather than left to the consumer, because the consumer's last resort is
    to call `record_failure`, which lands in this same function against the same missing
    thread — so the failure path raises too, the message is never acked, and one deleted
    thread leaves a job unacked until the broker's `consumer_timeout` redelivers it to fail
    the same way again.
    """
    conversation_id = int(str(job.payload.get("conversation_id", 0)))
    if not conversation_id:
        log.warning("job has no conversation to record against", extra={"job_id": job.job_id})
        return
    try:
        async with session_scope() as session:
            await AppRepository(session).upsert_turn(
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
            "thread was deleted while the job ran; nothing to record against",
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
