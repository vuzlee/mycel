"""The S3 client and presigned URLs, opened on first use."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import aioboto3

from mycel.core.config import Settings, get_settings

_session: aioboto3.Session | None = None
#: One open client per loop, so every operation reuses its connection pool.
_clients: dict[asyncio.AbstractEventLoop, tuple[AsyncExitStack, Any]] = {}


class ObjectsUnavailable(RuntimeError):
    """No object store is configured."""


def configured(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return bool(cfg.s3_endpoint_url and cfg.s3_access_key and cfg.s3_secret_key)


@asynccontextmanager
async def s3() -> AsyncIterator[Any]:
    global _session
    if not configured():
        raise ObjectsUnavailable("S3_ENDPOINT_URL, S3_ACCESS_KEY and S3_SECRET_KEY must be set")
    settings = get_settings()
    assert settings.s3_access_key and settings.s3_secret_key
    if _session is None:
        _session = aioboto3.Session(
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            region_name="us-east-1",
        )
    loop = asyncio.get_running_loop()
    if loop not in _clients:
        stack = AsyncExitStack()
        client = await stack.enter_async_context(
            _session.client("s3", endpoint_url=settings.s3_endpoint_url)
        )
        _clients[loop] = (stack, client)
    yield _clients[loop][1]


async def close() -> None:
    """Close this loop's client and forget those of closed loops."""
    for loop in [loop for loop in _clients if loop.is_closed()]:
        del _clients[loop]
    found = _clients.pop(asyncio.get_running_loop(), None)
    if found is not None:
        await found[0].aclose()


PRESIGN_SECONDS = 300


async def presign(bucket: str, key: str) -> str:
    """A time-limited GET URL, so the file never passes through the API."""
    async with s3() as client:
        url: str = await client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=PRESIGN_SECONDS
        )
        return url
