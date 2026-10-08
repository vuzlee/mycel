"""Citations of a finished knowledge answer, stored beside it."""

from typing import Any

from mycel.core.config import get_settings
from mycel.infra.redis import _kv
from mycel.infra.redis.client import get_client


async def store(job_id: str, user_id: int, sources: list[dict[str, Any]]) -> None:
    body = {"user_id": user_id, "sources": sources}
    await _kv.put(
        await get_client(), _kv.key("citations", job_id), body, get_settings().result_ttl_seconds
    )


async def fetch(job_id: str) -> dict[str, Any] | None:
    """`{"user_id", "sources"}`, or `None` before the answer is ready."""
    found: dict[str, Any] | None = await _kv.get(await get_client(), _kv.key("citations", job_id))
    return found
