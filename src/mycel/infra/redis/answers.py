"""Cached knowledge answers. The same question on an unchanged store costs nothing.

Keyed by the user's store version (document count and newest change) and by what wrote the
answer (prompt and models), so an upload, a prompt edit or a model swap makes every earlier
answer unreachable without deleting anything. Cache server.
"""

import hashlib
import json
from typing import Any

from mycel.infra.redis.client import get_cache_client

TTL_SECONDS = 24 * 3600


def normalise(question: str) -> str:
    return " ".join(question.lower().split()).rstrip("?.! ")


def writer(instructions: str, models: tuple[str, ...]) -> str:
    """A short fingerprint of what answers: the prompt and every model it may fall to."""
    return hashlib.sha256("\n".join((instructions, *models)).encode()).hexdigest()[:12]


def _key(owner_id: int, version: str, writer: str, question: str) -> str:
    digest = hashlib.sha256(normalise(question).encode()).hexdigest()[:32]
    return f"answer:{owner_id}:{version}:{writer}:{digest}"


async def get(owner_id: int, version: str, writer: str, question: str) -> dict[str, Any] | None:
    raw = await (await get_cache_client()).get(_key(owner_id, version, writer, question))
    if raw is None:
        return None
    found: dict[str, Any] = json.loads(raw)
    return found


async def put(
    owner_id: int, version: str, writer: str, question: str, result: dict[str, Any]
) -> None:
    await (await get_cache_client()).set(
        _key(owner_id, version, writer, question), json.dumps(result), ex=TTL_SECONDS
    )
