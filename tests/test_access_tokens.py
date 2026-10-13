"""An access token is refreshed once per lifetime, not once per call."""

from collections.abc import Iterator
from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from mycel.core.config import get_settings
from mycel.infra.redis import access_tokens as store
from mycel.services import access_tokens
from mycel.services.access_tokens import Fresh

pytestmark = pytest.mark.anyio


class Cache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.down = False

    async def get(self, key: str) -> str | None:
        if self.down:
            raise RedisConnectionError("down")
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int) -> None:
        if self.down:
            raise RedisConnectionError("down")
        self.values[key], self.ttls[key] = value, ex

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[Cache]:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    fake = Cache()

    async def client() -> Any:
        return fake

    monkeypatch.setattr(store, "get_cache_client", client)
    yield fake
    get_settings.cache_clear()


def _refresher(lifetime: int | None) -> tuple[list[int], Any]:
    calls: list[int] = []

    async def refresh() -> Fresh:
        calls.append(1)
        return f"token-{len(calls)}", lifetime

    return calls, refresh


async def test_two_calls_refresh_once(cache: Cache) -> None:
    calls, refresh = _refresher(3600)
    assert await access_tokens.cached("google", 7, refresh) == "token-1"
    assert await access_tokens.cached("google", 7, refresh) == "token-1"
    assert len(calls) == 1


async def test_it_expires_before_the_provider_says(cache: Cache) -> None:
    _, refresh = _refresher(3600)
    await access_tokens.cached("jira", 7, refresh)
    assert list(cache.ttls.values()) == [3600 - access_tokens.MARGIN_SECONDS]


async def test_the_token_is_not_stored_in_the_clear(cache: Cache) -> None:
    _, refresh = _refresher(3600)
    await access_tokens.cached("jira", 7, refresh)
    assert "token-1" not in next(iter(cache.values.values()))


async def test_no_lifetime_is_not_cached(cache: Cache) -> None:
    calls, refresh = _refresher(None)
    await access_tokens.cached("google", 7, refresh)
    await access_tokens.cached("google", 7, refresh)
    assert len(calls) == 2


async def test_people_and_providers_do_not_share(cache: Cache) -> None:
    calls, refresh = _refresher(3600)
    await access_tokens.cached("google", 7, refresh)
    await access_tokens.cached("google", 8, refresh)
    await access_tokens.cached("jira", 7, refresh)
    assert len(calls) == 3


async def test_forgetting_makes_the_next_call_refresh(cache: Cache) -> None:
    calls, refresh = _refresher(3600)
    await access_tokens.cached("jira", 7, refresh)
    await access_tokens.forget("jira", 7)
    await access_tokens.cached("jira", 7, refresh)
    assert len(calls) == 2


async def test_a_dead_cache_still_answers(cache: Cache) -> None:
    cache.down = True
    calls, refresh = _refresher(3600)
    assert await access_tokens.cached("google", 7, refresh) == "token-1"
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("payload", "seconds"),
    [
        ({"expires_in": 3599}, 3599),
        ({"expires_in": "3600"}, 3600),
        ({}, None),
        ({"expires_in": "x"}, None),
    ],
)
def test_the_lifetime_is_read_when_it_is_a_number(
    payload: dict[str, object], seconds: int | None
) -> None:
    assert access_tokens.lifetime(payload) == seconds
