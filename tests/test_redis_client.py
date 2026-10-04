"""Which Redis client a caller gets back, and why the loop is part of the question.

A `redis.Redis` holds sockets bound to the loop that opened them. Handing one to a second
loop raises `got Future attached to a different loop` and then `Event loop is closed`,
and neither message mentions the cache that produced it — it reads as a broken Redis.

One process runs several loops in practice: pytest opens one per test and `asyncio.run`
opens one per call. These tests pin the two halves of that: a client is reused inside one
loop, and never across two.

No server needed. `from_url` is lazy, so nothing here connects.
"""

import asyncio

import pytest

from mycel.core.config import get_settings
from mycel.infra.redis import client as module

pytestmark = pytest.mark.anyio

@pytest.fixture(autouse=True)
def empty() -> None:
    module._clients.clear()

class TestOneClientPerLoop:
    async def test_the_same_loop_gets_the_same_client(self) -> None:
        assert await module.get_client() is await module.get_client()

    async def test_the_two_urls_are_two_clients(self) -> None:
        """Results and cache live on servers with different eviction policies."""
        assert await module.get_client() is not await module.get_cache_client()

    def test_a_second_loop_gets_its_own(self) -> None:
        """The failure this keying exists for: a pool reused past the loop that opened it.

        Driven with `asyncio.run` rather than the anyio fixture because two separate loops
        is the whole point, and one test body only ever runs on one.
        """
        first = asyncio.run(module.get_client())
        second = asyncio.run(module.get_client())
        assert first is not second

    def test_a_closed_loop_does_not_keep_an_entry_alive(self) -> None:
        """Otherwise the dict grows by one dead pool per test in a long suite."""
        asyncio.run(module.get_client())
        asyncio.run(module.get_client())
        assert len(module._clients) == 1

class TestClosing:
    async def test_closing_forgets_what_it_closed(self) -> None:
        opened = await module.get_client()
        await module.close_clients()
        assert not module._clients
        assert await module.get_client() is not opened

    async def test_closing_when_nothing_was_opened_is_not_an_error(self) -> None:
        await module.close_clients()

    def test_a_dead_loop_s_client_is_dropped_rather_than_closed(self) -> None:
        """`aclose()` on a client from a dead loop is the very error being avoided.

        The stale entry is dropped on the next lookup, so the dict shrinks without
        anything being awaited on a loop that has ended. Synchronous, because driving two
        loops from inside a third is not something asyncio allows.
        """
        url = get_settings().redis_url

        dead = asyncio.new_event_loop()
        try:
            stale = dead.run_until_complete(module.get_client())
        finally:
            dead.close()
        assert (dead, url) in module._clients

        live = asyncio.new_event_loop()
        try:
            mine = live.run_until_complete(module.get_client())
            assert mine is not stale
            assert (dead, url) not in module._clients
            live.run_until_complete(module.close_clients())
        finally:
            live.close()
        assert not module._clients
