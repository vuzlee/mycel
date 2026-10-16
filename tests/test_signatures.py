"""Gemini thought signatures survive the round trip pydantic-ai drops them from."""

import json
from typing import Any

import httpx2
import pytest

from mycel.agents.core.signatures import SignatureTransport

URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
pytestmark = pytest.mark.anyio

SIG = {"google": {"thought_signature": "AY89a1"}}


def _call(**extra: Any) -> dict[str, Any]:
    return {"id": "call_1", "type": "function", "function": {"name": "run_sql"}, **extra}


def _followup() -> dict[str, Any]:
    """The next request, as pydantic-ai builds it: the call without its signature."""
    return {
        "messages": [
            {"role": "user", "content": "q"},
            {"role": "assistant", "tool_calls": [_call()]},
            {"role": "tool", "tool_call_id": "call_1", "content": "42"},
        ]
    }


class Provider:
    """Answers the first request with a signed call, records every request body."""

    def __init__(self, stream: bool) -> None:
        self.stream = stream
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.bodies.append(json.loads(request.content))
        if not self.stream:
            choice = {"message": {"role": "assistant", "tool_calls": [_call(extra_content=SIG)]}}
            return httpx2.Response(200, json={"choices": [choice]})
        # The signature and the id arrive in different deltas, as Gemini streams them.
        deltas = [
            {"tool_calls": [{"index": 0, "extra_content": SIG}]},
            {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "run_sql"}}]},
        ]
        lines = [f"data: {json.dumps({'choices': [{'delta': d}]})}\n\n" for d in deltas]
        body = ("".join(lines) + "data: [DONE]\n\n").encode()
        return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})


async def _round_trip(provider: Provider) -> dict[str, Any]:
    kept: dict[str, Any] = {}
    transport = SignatureTransport(httpx2.MockTransport(provider), kept)
    async with httpx2.AsyncClient(transport=transport) as client:
        first = await client.post(URL, json={"messages": [{"role": "user", "content": "q"}]})
        await first.aread()
        await client.post(URL, json=_followup())
    return provider.bodies[1]["messages"][1]["tool_calls"][0]


async def test_a_signature_comes_back_on_the_next_request() -> None:
    assert (await _round_trip(Provider(stream=False)))["extra_content"] == SIG


async def test_a_streamed_signature_comes_back_too() -> None:
    assert (await _round_trip(Provider(stream=True)))["extra_content"] == SIG


async def test_the_streamed_body_reaches_the_caller_unchanged() -> None:
    provider = Provider(stream=True)
    transport = SignatureTransport(httpx2.MockTransport(provider), {})
    async with httpx2.AsyncClient(transport=transport) as client:
        response = await client.post(URL, json={"messages": []})
        body = await response.aread()
    assert body.endswith(b"data: [DONE]\n\n")
    assert b"thought_signature" in body


async def test_a_provider_without_signatures_is_left_alone() -> None:
    def plain(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.content)
        return httpx2.Response(200, json={"choices": [{"message": {"tool_calls": [_call()]}}]})

    seen: list[bytes] = []
    transport = SignatureTransport(httpx2.MockTransport(plain), {})
    async with httpx2.AsyncClient(transport=transport) as client:
        await (await client.post(URL, json={"messages": []})).aread()
        await client.post(URL, json=_followup())
    assert b"extra_content" not in seen[1]
