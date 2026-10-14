"""The worker's consume loop: receive a job, run it, ack."""

import asyncio
import sys

from aio_pika.abc import AbstractExchange, AbstractIncomingMessage
from opentelemetry import context as otel_context

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.redis import deliveries, results
from mycel.queue import context, retry, topology
from mycel.queue.connection import channel
from mycel.queue.handler import Handler
from mycel.queue.job import Job

log = get_logger(__name__)

#: Low enough to spread jobs across workers, high enough to cover network waits.
PREFETCH = 2


async def handle(message: AbstractIncomingMessage, dlx: AbstractExchange, jobs: Handler) -> None:
    """Run one job, then ack; failures go to retry or dead-letter, never re-raised."""
    ctx = context.extract(dict(message.headers or {}))
    token = otel_context.attach(ctx) if ctx is not None else None
    try:
        await _handle(message, dlx, jobs)
    finally:
        if token is not None:
            otel_context.detach(token)


async def _handle(message: AbstractIncomingMessage, dlx: AbstractExchange, jobs: Handler) -> None:
    """The body of `handle`, with the caller's trace context already attached."""
    try:
        job = Job.model_validate_json(message.body)
    except ValueError as exc:
        # A malformed body will not parse on retry either, and has no job id.
        log.error("unreadable job body", extra={"message_id": message.message_id})
        await retry.reject(message, dlx, reason=f"unreadable job body: {exc}", give_up=True)
        return

    # Redelivered means a worker took it and never acked: it may be what killed that worker.
    if message.redelivered and await deliveries.count(job.job_id) > topology.MAX_ATTEMPTS:
        log.error("job keeps killing its worker", extra={"job_id": job.job_id})
        await jobs.record_failure(job, "worker died on every attempt")
        await retry.reject(message, dlx, reason="worker died on every attempt", give_up=True)
        return

    try:
        await results.mark_running(job.job_id)
        await jobs.run(job)
        await message.ack()
    except jobs.final as exc:
        # Another attempt cannot succeed (budget, a stuck model): straight to the dead-letter queue.
        log.warning("job failed for good", extra={"job_id": job.job_id, "error": repr(exc)})
        await jobs.record_failure(job, str(exc))
        await retry.reject(message, dlx, reason=str(exc), give_up=True)
    except jobs.transient as exc:
        # Transient: mark failed only on the last attempt, so pollers see `running`.
        if retry.exhausted(message):
            await jobs.record_failure(job, str(exc))
        await retry.reject(message, dlx, reason=str(exc))
    except Exception as exc:  # the loop must survive; see the docstring
        log.exception("job raised an unexpected error", extra={"job_id": job.job_id})
        await jobs.record_failure(job, repr(exc))
        await retry.reject(message, dlx, reason=repr(exc), give_up=True)


async def run_worker(
    jobs: Handler, stop: asyncio.Event | None = None, queue: str = topology.QUEUE
) -> None:
    """Consume until `stop` is set, then finish the job in flight."""
    stop = stop or asyncio.Event()

    ingest = queue == topology.INGEST_QUEUE
    budget = get_settings().ingest_worker_max_jobs if ingest else 0
    done = 0

    async with channel() as ch:
        await ch.set_qos(prefetch_count=1 if ingest else PREFETCH)
        topo = await topology.declare(ch)

        async def _on_message(message: AbstractIncomingMessage) -> None:
            nonlocal done
            await handle(message, topo.dlx, jobs)
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


def main(jobs: Handler, argv: list[str] | None = None) -> int:
    """Consume `--queue` (jobs by default) until SIGTERM, serving /metrics."""
    from mycel.lifecycle import running, start, stop_on_signals

    args = argv if argv is not None else sys.argv[1:]
    queue = args[args.index("--queue") + 1] if "--queue" in args else topology.QUEUE
    process = "ingest" if queue == topology.INGEST_QUEUE else "worker"
    start(process)

    async def _main() -> None:
        async with running(process):
            await run_worker(jobs, stop_on_signals(), queue)

    asyncio.run(_main())
    return 0
