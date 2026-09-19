"""Run the job layer against the real broker. The half `tests/test_queue.py` cannot prove.

    docker compose up -d rabbitmq redis
    uv run python -m mycel.queue.consumer          # in another terminal
    uv run python scripts/try_queue.py
    uv run python scripts/try_queue.py "how many tickets in Q2?"

The fakes in `tests/test_queue.py` believe whatever the consumer tells them. They cannot
tell the truth about the things only a broker decides: whether the exchange routes a key to
the queue we think it does, whether `jobs.retry` really expires back into `jobs` after its
TTL, or whether the declarations in `topology.py` match what is already on the server.

Not a test: it needs RabbitMQ, Redis, a model and a credential, so it stays out of `tests/`
where `ALLOW_MODEL_REQUESTS` is off.
"""

import asyncio
import sys

from mycel.core.config import get_settings
from mycel.core.logging import setup_logging
from mycel.observability.tracing import setup_tracing
from mycel.queue.connection import close_connection
from mycel.services.enqueue import enqueue_report
from mycel.storage.redis import results

QUESTION = "Revenue went 1,200,000 USD in Q1 to 1,410,000 USD in Q2. How much growth?"

#: A report runs for minutes. Long enough that a worker which never picked the job up is
#: visibly different from one still working, short enough to not hang a terminal forever.
TIMEOUT_S = 600
POLL_S = 2.0


async def _watch(job_id: str) -> int:
    """Poll the result store the way the API's GET endpoint does, and report what lands."""
    waited = 0.0
    last = ""

    while waited < TIMEOUT_S:
        result = await results.fetch(job_id)
        if result is None:
            # Before the worker's first write there is no key at all. After the TTL there
            # is no key either, which is exactly the ambiguity the API answers with a 404.
            state = "no result yet — is the worker running?"
        else:
            state = result.status

        if state != last:
            print(f"  [{waited:6.1f}s] {state}")
            last = state

        if result is not None and result.status == "done":
            print(f"\nspent: ${result.spent_usd}")
            for finding in (result.report or {}).get("findings", []):
                print(f"  - {finding['statement']}")
            return 0
        if result is not None and result.status == "failed":
            print(f"\nfailed: {result.error}")
            # Non-zero, but the run still told us what we came for: the job made it across
            # the broker and the failure came back through the result store.
            return 1

        await asyncio.sleep(POLL_S)
        waited += POLL_S

    print(f"\nnothing after {TIMEOUT_S}s — check the worker's log and `jobs.dlq`")
    return 1


async def _main() -> int:
    settings = get_settings()
    setup_logging(settings.log_level)
    provider = setup_tracing(settings)

    question = sys.argv[1] if len(sys.argv) > 1 else QUESTION
    print(f"broker: {settings.rabbitmq_url.rsplit('@', 1)[-1]}")
    print(f"asking: {question}\n")

    try:
        job_id = await enqueue_report(question)
        print(f"job_id: {job_id}\n")
        return await _watch(job_id)
    finally:
        # Both clients hold a socket open. Without this the script prints its answer and
        # then sits there, which reads as a hang rather than as a finished run.
        await close_connection()
        await results.close_client()
        if provider is not None:
            provider.shutdown()


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
