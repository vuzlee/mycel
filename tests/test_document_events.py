"""Document state changes reach the page over SSE, through a per-user Redis signal."""

import os

import pytest

import mycel.infra.redis.document_events as document_events

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not os.environ.get("REDIS_URL"), reason="no redis"),
]


class TestTheSignal:
    async def test_a_change_wakes_the_listener(self) -> None:
        listener = await document_events.Listener(990_001).open()
        await document_events.changed(990_001)
        assert await listener.next(timeout_s=2) is True
        await listener.close()

    async def test_silence_is_a_keepalive(self) -> None:
        stream = document_events.listen(990_002, timeout_s=0.2)
        assert await stream.__anext__() is False
        await stream.aclose()  # type: ignore[attr-defined]

    async def test_another_users_change_is_not_heard(self) -> None:
        listener = await document_events.Listener(990_003).open()
        await document_events.changed(990_004)
        assert await listener.next(timeout_s=0.5) is False
        await listener.close()
