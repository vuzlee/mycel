"""The session cookie cache: it saves a Postgres read, and never outlives a revoke."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisDown
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.principal import Principal
from mycel.infra.postgres.repositories.identity import IdentityRepository
from mycel.infra.redis import sessions
from mycel.services import auth
from tests.fakes import needs_postgres

pytestmark = pytest.mark.anyio


class CacheRedis:
    """get, set with a TTL, delete; every key it ever held is visible to the test."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}
        self.down = False

    def _check(self) -> None:
        if self.down:
            raise RedisDown("cache is down")

    async def get(self, key: str) -> str | None:
        self._check()
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._check()
        self.values[key] = value
        self.ttls[key] = ex
        return True

    async def delete(self, key: str) -> int:
        self._check()
        return 0 if self.values.pop(key, None) is None else 1


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> CacheRedis:
    fake = CacheRedis()

    async def client() -> CacheRedis:
        return fake

    monkeypatch.setattr(sessions, "get_cache_client", client)
    return fake


class TestTheKey:
    async def test_the_token_itself_is_never_stored(self, cache: CacheRedis) -> None:
        """The cookie is a credential; a dump of the cache must not hand one out."""
        await sessions.put("secret-cookie", Principal(id=1, email="a@example.com"), 60)
        assert not any(
            "secret-cookie" in key or "secret-cookie" in v for key, v in cache.values.items()
        )

    async def test_a_value_comes_back_as_a_principal(self, cache: CacheRedis) -> None:
        user = Principal(id=7, email="b@example.com")
        await sessions.put("t", user, 60)
        assert await sessions.get("t") == user


@needs_postgres
class TestRevoke:
    async def test_a_looked_up_cookie_is_cached_for_a_minute(
        self, session: AsyncSession, cache: CacheRedis
    ) -> None:
        user = await auth.account_for(session, "c@example.com")
        token = await auth.open_session(session, user.id)

        await auth.session_user(session, token)

        assert await auth.cached_user(token) == user
        assert list(cache.ttls.values()) == [int(auth.CACHE_FOR.total_seconds())]

    async def test_logging_out_drops_the_cached_cookie(
        self, session: AsyncSession, cache: CacheRedis
    ) -> None:
        """Without it a stolen cookie kept working for the cache's lifetime after logout."""
        user = await auth.account_for(session, "d@example.com")
        token = await auth.open_session(session, user.id)
        await auth.session_user(session, token)

        await auth.close_session(session, token)

        assert await auth.cached_user(token) is None

    async def test_logout_fails_loudly_when_the_cache_is_down(
        self, session: AsyncSession, cache: CacheRedis
    ) -> None:
        """A revoke that cleared Postgres but not the cache would look done and not be."""
        user = await auth.account_for(session, "e@example.com")
        token = await auth.open_session(session, user.id)
        await auth.session_user(session, token)
        cache.down = True

        with pytest.raises(RedisDown):
            await auth.close_session(session, token)

    async def test_the_cache_never_outlives_the_session(
        self, session: AsyncSession, cache: CacheRedis
    ) -> None:
        user = await auth.account_for(session, "f@example.com")
        soon = datetime.now(UTC) + timedelta(seconds=20)
        await IdentityRepository(session).create_session("ending-token", user.id, soon)

        await auth.session_user(session, "ending-token")

        assert all(ttl is not None and ttl <= 20 for ttl in cache.ttls.values())

    async def test_a_cache_outage_falls_back_to_postgres(
        self, session: AsyncSession, cache: CacheRedis
    ) -> None:
        """Reads keep working: the cache only saves a query."""
        user = await auth.account_for(session, "g@example.com")
        token = await auth.open_session(session, user.id)
        cache.down = True

        assert await auth.cached_user(token) is None
        assert await auth.session_user(session, token) == user


async def test_the_dependency_answers_from_the_cache_without_a_session(
    cache: CacheRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of the cache: a signed-in read opens no session just to name the caller."""
    from mycel.api import dependencies

    user = Principal(id=3, email="h@example.com")
    await sessions.put("cached-token", user, 60)

    def no_session() -> Any:
        raise AssertionError("opened a session for a cached cookie")

    monkeypatch.setattr(dependencies, "session_scope", no_session)
    assert await dependencies.signed_in("cached-token") == user
