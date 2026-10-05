"""Bucket declarations. Created on first use if missing."""

from mycel.core.config import get_settings
from mycel.infra.objects.client import s3

_ready: set[str] = set()


def documents() -> str:
    """Original files users upload."""
    return get_settings().documents_bucket


async def ensure(bucket: str) -> None:
    """Create the bucket once per process. Safe when it already exists."""
    if bucket in _ready:
        return
    async with s3() as client:
        existing = await client.list_buckets()
        if not any(b["Name"] == bucket for b in existing.get("Buckets", [])):
            await client.create_bucket(Bucket=bucket)
    _ready.add(bucket)
