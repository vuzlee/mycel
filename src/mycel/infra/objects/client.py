"""The S3 session and presigned URLs. Opened on first use, never at import."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aioboto3

from mycel.core.config import Settings, get_settings

_session: aioboto3.Session | None = None


class ObjectsUnavailable(RuntimeError):
    """No object store is configured."""


def configured(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return bool(cfg.s3_endpoint_url and cfg.s3_access_key and cfg.s3_secret_key)


@asynccontextmanager
async def s3() -> AsyncIterator[Any]:
    """One S3 client for the block. aiobotocore clients are cheap to open."""
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
    async with _session.client("s3", endpoint_url=settings.s3_endpoint_url) as client:
        yield client


PRESIGN_SECONDS = 300


async def presign(bucket: str, key: str) -> str:
    """A time-limited GET URL, so the file never passes through the API."""
    async with s3() as client:
        url: str = await client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=PRESIGN_SECONDS
        )
        return url
