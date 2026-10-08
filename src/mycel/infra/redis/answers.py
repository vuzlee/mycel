"""Cached knowledge answers, keyed by store version and by prompt and models."""

import hashlib
import json
from typing import Any

from mycel.infra.redis.client import get_cache_client

TTL_SECONDS = 24 * 3600


def normalise(question: str) -> str:
    return " ".join(question.lower().split()).rstrip("?.! ")


def writer(instructions: str, models: tuple[str, ...]) -> str:
    """A short fingerprint of the prompt and every model it may fall back to."""
    return hashlib.sha256("\n".join((instructions, *models)).encode()).hexdigest()[:12]


def _key(user_id: int, version: str, writer: str, question: str) -> str:
    digest = hashlib.sha256(normalise(question).encode()).hexdigest()[:32]
    return f"answer:{user_id}:{version}:{writer}:{digest}"


async def get(user_id: int, version: str, writer: str, question: str) -> dict[str, Any] | None:
    raw = await (await get_cache_client()).get(_key(user_id, version, writer, question))
    if raw is None:
        return None
    found: dict[str, Any] = json.loads(raw)
    return found


async def put(
    user_id: int, version: str, writer: str, question: str, result: dict[str, Any]
) -> None:
    await (await get_cache_client()).set(
        _key(user_id, version, writer, question), json.dumps(result), ex=TTL_SECONDS
    )
