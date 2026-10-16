"""Gemini 3 thought signatures, carried across the steps of one run.

Gemini's OpenAI-compatible endpoint sends a signature with each tool call, in
`tool_calls[].extra_content`, and refuses the next request with a 400 unless it comes back.
pydantic-ai drops the field (pydantic-ai#9947), so this transport keeps it by tool call id
and puts it back on the way out. Other providers never send it, and pass through untouched.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx2


class SignatureTransport(httpx2.AsyncBaseTransport):
    """Wraps one run's transport; `kept` is shared by every key of the model."""

    def __init__(self, inner: httpx2.AsyncBaseTransport, kept: dict[str, Any]) -> None:
        self._inner = inner
        self._kept = kept

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        request = self._put_back(request)
        response = await self._inner.handle_async_request(request)
        response.request = request
        if "event-stream" in response.headers.get("content-type", ""):
            return _rewrap(response, self._watch_stream(response.aiter_bytes()))
        if "json" in response.headers.get("content-type", ""):
            content = await response.aread()
            self._keep_from(json.loads(content or b"{}"), {})
            return _rewrap(response, _once(content))
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()

    def _put_back(self, request: httpx2.Request) -> httpx2.Request:
        if not self._kept or request.method != "POST":
            return request
        body = json.loads(request.content)
        changed = False
        for message in body.get("messages", []):
            for call in message.get("tool_calls") or []:
                extra = self._kept.get(call.get("id"))
                if extra is not None and "extra_content" not in call:
                    call["extra_content"] = extra
                    changed = True
        if not changed:
            return request
        headers = {k: v for k, v in request.headers.items() if k.lower() != "content-length"}
        return httpx2.Request(
            request.method, request.url, headers=headers, json=body, extensions=request.extensions
        )

    async def _watch_stream(self, raw: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        """Pass every byte on as it came; read each `data:` line on the side."""
        pending: dict[int, dict[str, Any]] = {}
        buffer = b""
        async for chunk in raw:
            yield chunk
            buffer += chunk
            *lines, buffer = buffer.split(b"\n")
            for line in lines:
                self._read_event(line, pending)
        self._read_event(buffer, pending)

    def _read_event(self, line: bytes, pending: dict[int, dict[str, Any]]) -> None:
        line = line.strip()
        if not line.startswith(b"data:") or line == b"data: [DONE]":
            return
        try:
            self._keep_from(json.loads(line[5:]), pending)
        except ValueError:
            return

    def _keep_from(self, payload: object, pending: dict[int, dict[str, Any]]) -> None:
        """A streamed call may name its id and its signature in different deltas."""
        if not isinstance(payload, dict):
            return  # Google's errors come as a list
        for choice in payload.get("choices") or []:
            part = choice.get("message") or choice.get("delta") or {}
            for position, call in enumerate(part.get("tool_calls") or []):
                slot = pending.setdefault(call.get("index", position), {})
                slot.update({k: call[k] for k in ("id", "extra_content") if call.get(k)})
                if "id" in slot and "extra_content" in slot:
                    self._kept[slot["id"]] = slot["extra_content"]


async def _once(content: bytes) -> AsyncIterator[bytes]:
    yield content


def _rewrap(response: httpx2.Response, stream: AsyncIterator[bytes]) -> httpx2.Response:
    """The same response, its body now read through `stream`, already decoded."""
    dropped = ("content-encoding", "content-length")
    headers = [(k, v) for k, v in response.headers.multi_items() if k.lower() not in dropped]
    return httpx2.Response(
        response.status_code,
        headers=headers,
        stream=_Stream(stream, response),
        request=response.request,
        extensions=response.extensions,
    )


class _Stream(httpx2.AsyncByteStream):
    def __init__(self, stream: AsyncIterator[bytes], original: httpx2.Response) -> None:
        self._stream = stream
        self._original = original

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._stream:
            yield chunk

    async def aclose(self) -> None:
        await self._original.aclose()
