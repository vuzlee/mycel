"""Past the cap the api answers 503 at once instead of queueing to the client timeout."""

import asyncio

import httpx
import pytest
from starlette.types import Receive, Scope, Send

from mycel.api.middleware import InFlightLimit


@pytest.mark.anyio
async def test_past_the_cap_answers_503_and_a_freed_slot_serves_again() -> None:
    release = asyncio.Event()

    async def slow(scope: Scope, receive: Receive, send: Send) -> None:
        await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = InFlightLimit(slow, limit=1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        first = asyncio.create_task(c.get("/projects"))
        await asyncio.sleep(0.01)
        refused = await c.get("/projects")
        probe = asyncio.create_task(c.get("/health/live"))
        await asyncio.sleep(0.01)
        release.set()
        assert (await first).status_code == 200
        assert (await probe).status_code == 200
        assert refused.status_code == 503
        assert refused.headers["retry-after"] == "1"
        assert refused.json()["error"] == "overloaded"
        assert (await c.get("/projects")).status_code == 200
