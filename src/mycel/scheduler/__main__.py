"""`python -m mycel.scheduler` — the third entrypoint, beside `api` and `worker`.

Its own process because its failure mode is its own: a scheduler that is down loses data
that a provider will not hand out twice, while an api that is down only loses requests
someone can repeat.
"""

import asyncio

from mycel.core.config import get_settings
from mycel.core.logging import get_logger, setup_logging
from mycel.infra.postgres.engine import dispose_engine
from mycel.observability.metrics_server import serve_metrics
from mycel.scheduler.runner import run_forever

log = get_logger(__name__)


async def _main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    # One port above the worker's: the two never share a machine in compose, but they do
    # on a laptop running both by hand.
    metrics = await serve_metrics(settings.metrics_port + 1, settings.metrics_host)
    try:
        await run_forever()
    finally:
        metrics.close()
        await dispose_engine()


def main() -> None:
    """Entrypoint. `KeyboardInterrupt` is a normal way to stop, not a crash."""
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        log.info("scheduler stopped")


if __name__ == "__main__":
    main()
