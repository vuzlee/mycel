"""Citations of a finished knowledge answer, stored beside it."""

import json
from typing import Any

from mycel.core.config import get_settings
from mycel.infra.redis.client import get_client


def _key(job_id: str) -> str:
    return f"mycel:citations:{job_id}"


async def store(job_id: str, user_id: int, sources: list[dict[str, Any]]) -> None:
    body = {"user_id": user_id, "sources": sources}
    await (await get_client()).set(
        _key(job_id), json.dumps(body), ex=get_settings().result_ttl_seconds
    )


async def fetch(job_id: str) -> dict[str, Any] | None:
    """`{"user_id", "sources"}`, or `None` before the answer is ready."""
    raw = await (await get_client()).get(_key(job_id))
    if raw is None:
        return None
    found: dict[str, Any] = json.loads(raw)
    return found
