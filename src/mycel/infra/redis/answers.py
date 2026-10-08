"""Cached knowledge answers, keyed by store version and by prompt and models."""

import hashlib
from typing import Any

from mycel.infra.redis import _kv
from mycel.infra.redis.client import get_cache_client

TTL_SECONDS = 24 * 3600


def normalise(question: str) -> str:
    return " ".join(question.lower().split()).rstrip("?.! ")


def writer(instructions: str, models: tuple[str, ...]) -> str:
    """A short fingerprint of the prompt and every model it may fall back to."""
    return hashlib.sha256("\n".join((instructions, *models)).encode()).hexdigest()[:12]


def _key(user_id: int, version: str, writer: str, question: str) -> str:
    digest = hashlib.sha256(normalise(question).encode()).hexdigest()[:32]
    return _kv.key("answer", user_id, version, writer, digest)


async def get(user_id: int, version: str, writer: str, question: str) -> dict[str, Any] | None:
    found: dict[str, Any] | None = await _kv.get(
        await get_cache_client(), _key(user_id, version, writer, question)
    )
    return found


async def put(
    user_id: int, version: str, writer: str, question: str, result: dict[str, Any]
) -> None:
    await _kv.put(
        await get_cache_client(), _key(user_id, version, writer, question), result, TTL_SECONDS
    )
