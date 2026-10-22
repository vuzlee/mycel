"""`python -m mycel.worker [--queue ingest]`: the worker process."""

import asyncio
import os
import sys

from mycel.lifecycle import running, start, stop_on_signals
from mycel.queue import consumer, topology
from mycel.queue.handler import Handler
from mycel.worker.handlers import HANDLER


def main(jobs: Handler, argv: list[str] | None = None) -> int:
    """Consume `--queue` (jobs by default) until SIGTERM, serving /metrics."""
    args = argv if argv is not None else sys.argv[1:]
    queue = args[args.index("--queue") + 1] if "--queue" in args else topology.QUEUE
    process = "ingest" if queue == topology.INGEST_QUEUE else "worker"
    start(process)

    async def _main() -> bool:
        async with running(process):
            return await consumer.run_worker(jobs, stop_on_signals(), queue)

    if asyncio.run(_main()):
        # A fresh process image gives docling's memory back without a container restart,
        # which Kubernetes would back off.
        os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(HANDLER))
