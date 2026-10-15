"""The worker's consume loop: receive a job, run it, ack."""

import asyncio
import time

from aio_pika.abc import AbstractExchange, AbstractIncomingMessage
from opentelemetry import context as otel_context

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.redis import deliveries, results
from mycel.observability.metrics import job_attempts, start_job_series
from mycel.queue import context, retry, topology
from mycel.queue.connection import channel
from mycel.queue.handler import Handler
from mycel.queue.inflight import InFlight
from mycel.queue.job import INGEST_KINDS, Job, JobKind

log = get_logger(__name__)

#: Low enough to spread jobs across workers, high enough to cover network waits.
PREFETCH = 2


async def handle(message: AbstractIncomingMessage, dlx: AbstractExchange, jobs: Handler) -> None:
    """Run one job, then ack; failures go to retry or dead-letter, never re-raised."""
    ctx = context.extract(dict(message.headers or {}))
    token = otel_context.attach(ctx) if ctx is not None else None
    try:
        await _handle(message, dlx, jobs)
    except Exception:
        # The failure path itself failed (the broker or Postgres went away): give the message
        # back rather than hold a prefetch slot until the broker's consumer timeout.
        log.exception("job could not be settled; returned to the queue")
        try:
            await message.nack(requeue=True)
        except Exception:
            log.exception("nack failed; the broker redelivers when the channel closes")
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
        await _record(jobs, job, "worker died on every attempt")
        await retry.reject(message, dlx, reason="worker died on every attempt", give_up=True)
        return

    started = time.monotonic()
    outcome = "failed"
    try:
        await results.mark_running(job.job_id)
        await jobs.run(job)
        await message.ack()
        outcome = "done"
    except jobs.final as exc:
        # Another attempt cannot succeed (budget, a stuck model): straight to the dead-letter queue.
        log.warning("job failed for good", extra={"job_id": job.job_id, "error": repr(exc)})
        await _record(jobs, job, str(exc))
        await retry.reject(message, dlx, reason=str(exc), give_up=True)
    except jobs.transient as exc:
        # Transient: mark failed only on the last attempt, so pollers see `running`.
        outcome = "retried"
        if retry.exhausted(message):
            await _record(jobs, job, str(exc))
        await retry.reject(message, dlx, reason=str(exc))
    except Exception as exc:  # the loop must survive; see the docstring
        log.exception("job raised an unexpected error", extra={"job_id": job.job_id})
        await _record(jobs, job, repr(exc))
        await retry.reject(message, dlx, reason=repr(exc), give_up=True)
    finally:
        job_attempts.labels(kind=str(job.kind), outcome=outcome).observe(time.monotonic() - started)


async def _record(jobs: Handler, job: Job, error: str) -> None:
    """Best effort: a store that is down must not stop the message being settled."""
    try:
        await jobs.record_failure(job, error)
    except Exception:
        log.exception("could not record the failure", extra={"job_id": job.job_id})


async def run_worker(
    jobs: Handler, stop: asyncio.Event | None = None, queue: str = topology.QUEUE
) -> bool:
    """Consume until `stop` is set, then finish the jobs in flight. True: stopped to recycle."""
    stop = stop or asyncio.Event()

    settings = get_settings()
    ingest = queue == topology.INGEST_QUEUE
    budget = settings.ingest_worker_max_jobs if ingest else 0
    done = 0
    inflight = InFlight()
    start_job_series([str(k) for k in JobKind if (k in INGEST_KINDS) == ingest])

    async with channel() as ch:
        await ch.set_qos(prefetch_count=1 if ingest else PREFETCH)
        topo = await topology.declare(ch)

        async def _on_message(message: AbstractIncomingMessage) -> None:
            nonlocal done
            await handle(message, topo.dlx, jobs)
            done += 1
            # docling keeps native memory it never gives back; stop, then re-exec.
            if budget and done >= budget:
                log.info("ingest worker recycling", extra={"jobs": done})
                stop.set()

        source = topo.ingest if ingest else topo.jobs
        tag = await source.consume(inflight.track(_on_message), no_ack=False)
        log.info("worker ready", extra={"queue": queue})

        await stop.wait()
        # Closing the channel cancels the handlers, so stop taking jobs and let them finish.
        await source.cancel(tag)
        left = await inflight.drain(settings.worker_drain_seconds)
        log.info("worker stopping", extra={"jobs_cut_short": left})
    return bool(budget) and done >= budget
