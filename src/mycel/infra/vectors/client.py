"""Shared Qdrant client and fastembed models, opened on first use; the only SDK import site."""

from collections.abc import Sequence
from functools import lru_cache

from qdrant_client import AsyncQdrantClient

from mycel.core.config import Settings, get_settings
from mycel.core.logging import get_logger

log = get_logger(__name__)

_client: AsyncQdrantClient | None = None


class VectorsUnavailable(RuntimeError):
    """Qdrant is not configured. Raised where the caller can still carry on without it."""


def configured(settings: Settings | None = None) -> bool:
    """Whether this deployment has Qdrant, checked before a search tool is offered."""
    return bool((settings or get_settings()).qdrant_url.strip())


def client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        url = get_settings().qdrant_url.strip()
        if not url:
            raise VectorsUnavailable("QDRANT_URL is unset; search over gold is disabled")
        _client = AsyncQdrantClient(url=url)
        log.info("qdrant client opened", extra={"url": url})
    return _client


async def close() -> None:
    """Close the client. Safe to call twice."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


@lru_cache(maxsize=4)
def _model(name: str):  # type: ignore[no-untyped-def]  # fastembed ships no stubs
    """One loaded model per name, per process."""
    from fastembed import TextEmbedding

    log.info("loading embedding model", extra={"model": name})
    return TextEmbedding(model_name=name, cache_dir=get_settings().embedding_cache_dir)


def embed(texts: Sequence[str], model: str | None = None) -> list[list[float]]:
    """Text to vectors, in order. CPU-bound; async callers use `asyncio.to_thread`."""
    if not texts:
        return []
    name = model or get_settings().embedding_model
    return [vector.tolist() for vector in _model(name).embed(list(texts))]
