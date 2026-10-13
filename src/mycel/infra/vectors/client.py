"""Shared Qdrant client and fastembed models, opened on first use; the only SDK import site."""

from collections.abc import Sequence
from functools import lru_cache

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import KeywordIndexParams, PayloadSchemaType, VectorParams

from mycel.core.config import Settings, get_settings
from mycel.core.logging import get_logger

log = get_logger(__name__)

_client: AsyncQdrantClient | None = None

#: What `create_payload_index` accepts as a field schema.
PayloadSchema = PayloadSchemaType | KeywordIndexParams

#: Collections known to exist on the open client; cleared when it closes.
_ensured: set[str] = set()


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
    _ensured.clear()


async def ensure(
    name: str, params: VectorParams, indexes: Sequence[tuple[str, PayloadSchema]] = ()
) -> str:
    """Create `name` and its payload indexes once per open client. Idempotent on Qdrant."""
    if name in _ensured:
        return name
    qdrant = client()
    if not await qdrant.collection_exists(name):
        await qdrant.create_collection(name, vectors_config=params)
        log.info("created collection", extra={"collection": name, "dimensions": params.size})
    # Re-declared on each first use: older collections may lack a newer index.
    for field, schema in indexes:
        await qdrant.create_payload_index(name, field, field_schema=schema)
    _ensured.add(name)
    return name


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
