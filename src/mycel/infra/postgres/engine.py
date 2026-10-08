"""One async engine per process, built on first use from a plain `postgresql://` DSN."""

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
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_engine.cache_clear()
