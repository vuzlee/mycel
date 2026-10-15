"""What a key test found, held for its owner to read. Hints and error kinds only, never keys."""

from typing import Any

from mycel.core.config import get_settings
from mycel.infra.redis import _kv
from mycel.infra.redis.client import get_client


def _key(job_id: str) -> str:
    return _kv.key("keycheck", job_id)


async def store(job_id: str, owner_id: int, checks: list[dict[str, Any]]) -> None:
    body = {"user_id": owner_id, "checks": checks}
    await _kv.put(await get_client(), _key(job_id), body, get_settings().result_ttl_seconds)


async def fetch(job_id: str) -> dict[str, Any] | None:
    """`{"user_id", "checks"}`, or None while the test is still running."""
    found: dict[str, Any] | None = await _kv.get(await get_client(), _key(job_id))
    return found
