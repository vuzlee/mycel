"""One shared Qdrant client and one shared embedding model, both opened on first use.

This is the only file that imports Qdrant's SDK or fastembed — the same confinement that
keeps every provider SDK inside `agents/core/model_builder.py`. Swapping either leaves the
rest of the system unaware.

**Not at import.** Importing this package must not require Qdrant to be up or a 130 MiB
model to be on disk, or every test and every `--help` needs both. `infra/redis/client.py`
makes the same choice for the same reason.

**Loading the model is slow once, then free.** fastembed reads ONNX weights off disk and
starts a runtime session; doing that per call would cost seconds on every search. One
instance per process, held for the life of it.
"""

from collections.abc import Sequence
from functools import lru_cache

from qdrant_client import AsyncQdrantClient

from mycel.core.config import get_settings
from mycel.core.logging import get_logger

log = get_logger(__name__)

_client: AsyncQdrantClient | None = None


class VectorsUnavailable(RuntimeError):
    """Qdrant is not configured. Raised where the caller can still carry on without it."""


def configured() -> bool:
    """Whether this deployment has somewhere to search.

    Checked before a tool is offered rather than inside it: a tool the model can see is a
    tool it will call, and a tool that fails every time costs a model turn to learn that.
    """
    return bool(get_settings().qdrant_url.strip())


def client() -> AsyncQdrantClient:
    """The shared client. Opened on first use, never at import."""
    global _client
    if _client is None:
        url = get_settings().qdrant_url.strip()
        if not url:
            raise VectorsUnavailable("QDRANT_URL is unset; search over gold is disabled")
        _client = AsyncQdrantClient(url=url)
        log.info("qdrant client opened", extra={"url": url})
    return _client


async def close() -> None:
    """Let a process exit without leaving a connection open. Safe to call twice."""
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
    """Text to vectors, in the order given.

    Synchronous and CPU-bound — an async caller wraps it in `asyncio.to_thread`.
    `model` defaults to the gold-search model.
    """
    if not texts:
        return []
    name = model or get_settings().embedding_model
    return [vector.tolist() for vector in _model(name).embed(list(texts))]
