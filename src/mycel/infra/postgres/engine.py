"""One async engine per process, built on first use from a plain `postgresql://` DSN."""

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mycel.core.config import get_settings

_ASYNC_DRIVER = "postgresql+asyncpg://"

#: A starved pool fails fast rather than holding a request for SQLAlchemy's default 30 s.
POOL_TIMEOUT_SECONDS = 10


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
        max_overflow=settings.db_max_overflow,
        pool_timeout=POOL_TIMEOUT_SECONDS,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_probe_engine() -> AsyncEngine:
    """One connection for readiness, apart from the request pool.

    A probe that queues behind requests on a busy pod times out, and the pod leaves the
    Service while it is merely slow: every caller then gets 503 from the ingress.
    """
    return create_async_engine(
        async_dsn(get_settings().database_url),
        pool_size=1,
        max_overflow=0,
        pool_timeout=POOL_TIMEOUT_SECONDS,
        pool_pre_ping=True,
    )


async def dispose_engine() -> None:
    for engine in (get_engine, get_probe_engine):
        if engine.cache_info().currsize:
            await engine().dispose()
        engine.cache_clear()
