"""One engine per process, built on first use.

The DSN is stored in the plain `postgresql://` form so alembic and psql can read the same
variable; the async driver is swapped in here.

Pool size is per process, not per deployment: `api` runs N uvicorn workers and `worker`
scales by consumer count, each holding its own pool. Summed past Postgres's
`max_connections`, the failure only appears under load.
"""

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mycel.core.config import get_settings

_ASYNC_DRIVER = "postgresql+asyncpg://"


def async_dsn(url: str) -> str:
    """Rewrite a plain DSN onto the async driver, leaving an explicit one alone."""
    if url.startswith("postgresql+"):
        return url
    return url.replace("postgresql://", _ASYNC_DRIVER, 1)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """The process-wide engine. Cached; call `get_engine.cache_clear()` in tests."""
    settings = get_settings()
    return create_async_engine(
        async_dsn(settings.database_url),
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,
    )


async def dispose_engine() -> None:
    """Close the pool and forget the engine, so the next call builds a fresh one."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_engine.cache_clear()
