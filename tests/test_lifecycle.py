"""Every process leaves through one exit that closes every store, even past a failure."""

import asyncio
import os
import signal
from typing import Any

import pytest

from mycel import lifecycle

pytestmark = pytest.mark.anyio


@pytest.fixture
def closed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def closer(name: str, fail: bool = False) -> Any:
        async def close() -> None:
            seen.append(name)
            if fail:
                raise ConnectionError(name)

        return close

    monkeypatch.setattr(
        lifecycle,
        "CLOSERS",
        tuple((n, closer(n, fail=n == "redis")) for n, _ in lifecycle.CLOSERS),
    )

    class Server:
        def close(self) -> None:
            seen.append("metrics")

    async def serve(port: int, host: str) -> Server:
        return Server()

    monkeypatch.setattr(lifecycle, "serve_metrics", serve)
    return seen


async def test_leaving_closes_every_store_even_when_one_fails(closed: list[str]) -> None:
    async with lifecycle.running("worker"):
        pass
    assert closed == ["metrics", "broker", "redis", "postgres", "qdrant"]


async def test_a_crash_inside_still_closes_everything(closed: list[str]) -> None:
    with pytest.raises(RuntimeError):
        async with lifecycle.running("scheduler"):
            raise RuntimeError("tick blew up")
    assert closed[-4:] == ["broker", "redis", "postgres", "qdrant"]


async def test_sigterm_sets_the_stop_event() -> None:
    stop = lifecycle.stop_on_signals()
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(stop.wait(), timeout=1)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.remove_signal_handler(sig)


def test_every_process_has_its_own_metrics_port() -> None:
    offsets = lifecycle.METRICS_OFFSET
    assert set(offsets) == {"api", "worker", "ingest", "scheduler"}
    assert len(set(offsets.values())) == len(offsets)
