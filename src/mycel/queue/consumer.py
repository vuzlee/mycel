"""The worker's consume loop: receive a job, run it, ack.

    uv run python -m mycel.queue.consumer

Three settings have to be got right here, and all three fail silently:

  no_ack=False          acking on delivery acks before the job finishes -> a worker dying
                        mid-job loses it
  ack after finishing   the order is: run, then ack. Not the reverse
  prefetch_count        set it low (1-2). Unbounded, one worker takes every queued message
                        and the others idle while it works through them one at a time

A failed job is **not** `nack`-ed with `requeue=True` — that returns it to the head of the
queue and it fails again immediately, spinning. `retry.reject` republishes it through the
dead-letter exchange instead.

Jobs that run for a long time age against the broker's `consumer_timeout` (30 minutes by
default) while unacked. Exceed it and the channel is closed and the job is redelivered, so
raise the value on the broker for anything that can run longer.

Call `context.extract()` on receipt, before running, so the job's span attaches to the span
of the request that created it.

**Shutdown is not an afterthought.** On SIGTERM the loop stops taking new messages and lets
the one in flight finish, because a report killed halfway is a report that gets redelivered
and paid for twice.
"""

import asyncio
import signal

from aio_pika.abc import AbstractExchange, AbstractIncomingMessage
from opentelemetry import context as otel_context

from mycel.agents.core import runner
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.exceptions import AgentError
from mycel.agents.orchestrator import Orchestrator
from mycel.agents.registry import build_deps
from mycel.core.config import get_settings
from mycel.core.logging import get_logger, setup_logging
from mycel.llm.budget import BudgetExceeded
from mycel.observability.tracing import setup_tracing
from mycel.queue import context, retry, topology
from mycel.queue.connection import channel, close_connection
from mycel.queue.job import Job, JobKind
from mycel.storage.redis import results

log = get_logger(__name__)

#: Two at a time: enough that a worker is not idle during the network waits an agent run is
#: mostly made of, low enough that a queue with four jobs and two workers gives each worker
#: two rather than one worker all four.
PREFETCH = 2


async def handle(message: AbstractIncomingMessage, dlx: AbstractExchange) -> None:
    """Run one job, then ack. Any failure is routed onward, never re-raised.

    Letting an exception escape would kill the consumer for one bad job, which is the
    outcome the retry queues exist to avoid.
    """
    ctx = context.extract(dict(message.headers or {}))
    token = otel_context.attach(ctx) if ctx is not None else None
    try:
        await _handle(message, dlx)
    finally:
        if token is not None:
            otel_context.detach(token)


async def _handle(message: AbstractIncomingMessage, dlx: AbstractExchange) -> None:
    """The body of `handle`, with the caller's trace context already attached."""
    try:
        job = Job.model_validate_json(message.body)
    except ValueError as exc:
        # A malformed body will be just as malformed in a minute, so it skips the retry
        # queue. There is no job id to record the failure against.
        log.error("unreadable job body", extra={"message_id": message.message_id})
        await retry.reject(message, dlx, reason=f"unreadable job body: {exc}", give_up=True)
        return

    try:
        await results.mark_running(job.job_id)
        await _run(job)
        await message.ack()
    except BudgetExceeded as exc:
        # Out of money is not transient: another attempt spends money the job does not
        # have. Straight to the dead-letter queue.
        log.warning("job refused for budget", extra={"job_id": job.job_id})
        await results.store_failure(job.job_id, str(exc))
        await retry.reject(message, dlx, reason=str(exc), give_up=True)
    except (AgentError, OSError) as exc:
        # A provider 503, a rate limit, a broken socket: worth another attempt in a minute.
        # The result is only marked failed on the last one, so a caller polling in between
        # sees `running` rather than a failure that is about to be retried.
        if retry.exhausted(message):
            await results.store_failure(job.job_id, str(exc))
        await retry.reject(message, dlx, reason=str(exc))
    except Exception as exc:  # noqa: BLE001 - see the docstring: the loop must survive
        log.exception("job raised an unexpected error", extra={"job_id": job.job_id})
        await results.store_failure(job.job_id, repr(exc))
        await retry.reject(message, dlx, reason=repr(exc), give_up=True)


async def _run(job: Job) -> None:
    """Do the work a job asks for, and record what came back."""
    if job.kind is not JobKind.REPORT:
        raise ValueError(f"no handler for job kind {job.kind!r}")

    question = str(job.payload.get("question", "")).strip()
    if not question:
        raise ValueError("report job has no question")

    settings = AgentSettings.from_config("orchestrator")
    deps = build_deps(job.job_id, ceiling_usd=get_settings().job_ceiling_usd, settings=settings)

    log.info("job started", extra={"job_id": job.job_id, "model": settings.model_spec})
    report = await runner.run(Orchestrator.build(settings), question, deps)
    await results.store(job.job_id, report, str(deps.budget.spent_usd))
    log.info(
        "job finished",
        extra={
            "job_id": job.job_id,
            "findings": len(report.findings),
            "gaps": len(report.gaps),
            "spent_usd": str(deps.budget.spent_usd),
        },
    )


async def run_worker(stop: asyncio.Event | None = None) -> None:
    """Consume until told to stop, then finish the job in flight and leave.

    Takes the stop event as an argument so a test can drive the loop without sending the
    test runner a signal.
    """
    stop = stop or asyncio.Event()

    async with channel() as ch:
        await ch.set_qos(prefetch_count=PREFETCH)
        topo = await topology.declare(ch)

        # `no_ack=False` is the default and stated anyway: the one setting here whose wrong
        # value loses jobs rather than merely slowing things down.
        async def _on_message(message: AbstractIncomingMessage) -> None:
            await handle(message, topo.dlx)

        await topo.jobs.consume(_on_message, no_ack=False)
        log.info("worker ready", extra={"queue": topology.QUEUE, "prefetch": PREFETCH})

        await stop.wait()
        log.info("worker stopping")


def main() -> int:
    """Entry point for `python -m mycel.queue.consumer`."""
    settings = get_settings()
    setup_logging(settings.log_level)
    provider = setup_tracing(settings)

    async def _main() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            # A signal handler on the loop rather than `signal.signal`: the latter runs the
            # handler between bytecodes, which cannot set an asyncio event safely.
            loop.add_signal_handler(sig, stop.set)

        try:
            await run_worker(stop)
        finally:
            await close_connection()
            await results.close_client()

    try:
        asyncio.run(_main())
    finally:
        if provider is not None:
            provider.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
