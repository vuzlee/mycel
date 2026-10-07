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
the one in flight finish, because a run killed halfway is a run that gets redelivered
and paid for twice.
"""

import asyncio
import signal
import sys

from aio_pika.abc import AbstractExchange, AbstractIncomingMessage
from opentelemetry import context as otel_context

from mycel.agents.core.exceptions import AgentError
from mycel.core.config import get_settings
from mycel.core.logging import get_logger, setup_logging
from mycel.domains import chat as chat_domain
from mycel.domains import ingest as ingest_domain
from mycel.infra.redis import results
from mycel.infra.redis.client import close_clients
from mycel.llm.budget import BudgetExceeded
from mycel.observability.metrics_server import serve_metrics
from mycel.observability.tracing import setup_tracing
from mycel.queue import context, retry, topology
from mycel.queue.connection import channel, close_connection
from mycel.queue.job import INGEST_KINDS, Job, JobKind

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
        await _record_failure(job, str(exc))
        await retry.reject(message, dlx, reason=str(exc), give_up=True)
    except (AgentError, OSError) as exc:
        # A provider 503, a rate limit, a broken socket: worth another attempt in a minute.
        # The result is only marked failed on the last one, so a caller polling in between
        # sees `running` rather than a failure that is about to be retried.
        if retry.exhausted(message):
            await _record_failure(job, str(exc))
        await retry.reject(message, dlx, reason=str(exc))
    except Exception as exc:  # the loop must survive; see the docstring
        log.exception("job raised an unexpected error", extra={"job_id": job.job_id})
        await _record_failure(job, repr(exc))
        await retry.reject(message, dlx, reason=repr(exc), give_up=True)


async def _run(job: Job) -> None:
    """Hand the job to the domain that knows what its kind means.

    One line on purpose. Until batch 013 this function built the orchestrator, seeded its
    budget and stored its result — the order of steps for one kind of work, written in the
    transport layer, where a second kind would have meant a second copy of it.
    """
    if job.kind is JobKind.INGEST:
        await ingest_domain.run(job)
    elif job.kind is JobKind.DELETE_DOCUMENT:
        await ingest_domain.delete(job)
    else:
        await chat_domain.run(job)


async def _record_failure(job: Job, error: str) -> None:
    """Each domain records its own failure where its caller looks for it."""
    if job.kind in INGEST_KINDS:
        await ingest_domain.record_failure(job, error)
    else:
        await chat_domain.record_failure(job, error)


async def run_worker(stop: asyncio.Event | None = None, queue: str = topology.QUEUE) -> None:
    """Consume until told to stop, then finish the job in flight and leave.

    Takes the stop event as an argument so a test can drive the loop without sending the
    test runner a signal.
    """
    stop = stop or asyncio.Event()

    ingest = queue == topology.INGEST_QUEUE
    budget = get_settings().ingest_worker_max_jobs if ingest else 0
    done = 0

    async with channel() as ch:
        await ch.set_qos(prefetch_count=1 if ingest else PREFETCH)
        topo = await topology.declare(ch)

        # `no_ack=False` is the default and stated anyway: the one setting here whose wrong
        # value loses jobs rather than merely slowing things down.
        async def _on_message(message: AbstractIncomingMessage) -> None:
            nonlocal done
            await handle(message, topo.dlx)
            done += 1
            # docling keeps native memory it never gives back; exit and be restarted.
            if budget and done >= budget:
                log.info("ingest worker recycling", extra={"jobs": done})
                stop.set()

        source = topo.ingest if ingest else topo.jobs
        await source.consume(_on_message, no_ack=False)
        log.info("worker ready", extra={"queue": queue})

        await stop.wait()
        log.info("worker stopping")


def main(argv: list[str] | None = None) -> int:
    """Entry point for `python -m mycel.queue.consumer [--queue ingest]`."""
    args = argv if argv is not None else sys.argv[1:]
    queue = args[args.index("--queue") + 1] if "--queue" in args else topology.QUEUE
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

        # The worker is where jobs actually run, so it is the process whose numbers matter
        # most — and the only reason it has a port at all.
        port = settings.metrics_port + (2 if queue == topology.INGEST_QUEUE else 0)
        metrics = await serve_metrics(port, settings.metrics_host)
        try:
            await run_worker(stop, queue)
        finally:
            metrics.close()
            await close_connection()
            await close_clients()

    try:
        asyncio.run(_main())
    finally:
        if provider is not None:
            provider.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
