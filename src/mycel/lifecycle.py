"""How every process starts and stops: logging, tracing, /metrics, then every store closed."""

import asyncio
import signal
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from mycel.agents.core.model_builder import close_clients as close_models
from mycel.core.config import get_settings
from mycel.core.logging import get_logger, setup_logging
from mycel.infra.http import close_clients as close_http
from mycel.infra.objects.client import close as close_objects
from mycel.infra.postgres.engine import dispose_engine
from mycel.infra.redis.client import close_clients
from mycel.infra.vectors.client import close as close_vectors
from mycel.observability.metrics_server import serve_metrics
from mycel.observability.tracing import setup_tracing
from mycel.queue.connection import close_connection

log = get_logger(__name__)

#: Each process's /metrics port, as an offset from `METRICS_PORT`, so all four fit one host.
METRICS_OFFSET = {"worker": 0, "scheduler": 1, "ingest": 2, "api": 3}

#: Closed in this order on the way out; each one is safe when it was never opened.
CLOSERS: tuple[tuple[str, Callable[[], Awaitable[None]]], ...] = (
    ("broker", close_connection),
    ("redis", close_clients),
    ("postgres", dispose_engine),
    ("qdrant", close_vectors),
    ("models", close_models),
    ("http", close_http),
    ("s3", close_objects),
)


def start(process: str) -> None:
    """Logging and tracing, before anything that logs or makes a span."""
    settings = get_settings()
    setup_logging(settings.log_level)
    setup_tracing(settings)


@asynccontextmanager
async def running(process: str) -> AsyncIterator[None]:
    """Serve /metrics for the block; close every store after it, whatever happened."""
    settings = get_settings()
    metrics = await serve_metrics(
        settings.metrics_port + METRICS_OFFSET[process], settings.metrics_host
    )
    try:
        yield
    finally:
        metrics.close()
        await close_all()
        log.info("%s stopped", process)


async def close_all() -> None:
    """Every store, each guarded: one that fails to close must not keep the rest open."""
    for name, close in CLOSERS:
        try:
            await close()
        except Exception:
            log.warning("could not close %s", name, exc_info=True)
    _flush_traces()


def stop_on_signals() -> asyncio.Event:
    """An event set by SIGTERM or SIGINT; the process finishes its work and exits."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    return stop


def _flush_traces() -> None:
    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    if callable(shutdown):
        shutdown()
