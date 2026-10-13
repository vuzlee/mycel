"""`python -m mycel.scheduler`: the scheduler process."""

import asyncio
from contextlib import suppress

from mycel.lifecycle import running, start, stop_on_signals
from mycel.scheduler.runner import run_forever


async def _main() -> None:
    async with running("scheduler"):
        stop = stop_on_signals()
        timers = asyncio.create_task(run_forever())
        await asyncio.wait(
            {timers, asyncio.create_task(stop.wait())}, return_when="FIRST_COMPLETED"
        )
        timers.cancel()
        with suppress(asyncio.CancelledError):
            await timers


def main() -> None:
    start("scheduler")
    asyncio.run(_main())


if __name__ == "__main__":
    main()
