"""Login, signup, reset and chat are capped per minute; a dead Redis lets requests through."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from mycel.api import limits
from mycel.core.config import get_settings
from mycel.infra.redis import rate


class Counter:
    """`rate.hit` against a dict; one window that never ends."""

    def __init__(self) -> None:
        self.counts: dict[tuple[str, str], int] = {}
        self.down = False

    async def hit(self, scope: str, key: str) -> tuple[int, int]:
        if self.down:
            raise RedisConnectionError("down")
        self.counts[scope, key] = self.counts.get((scope, key), 0) + 1
        return self.counts[scope, key], 42


@pytest.fixture
def counter(monkeypatch: pytest.MonkeyPatch) -> Counter:
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "true")
    get_settings.cache_clear()
    fake = Counter()
    monkeypatch.setattr(rate, "hit", fake.hit)
    return fake


@pytest.fixture
def app() -> Iterator[TestClient]:
    api = FastAPI()

    @api.post("/login", dependencies=[limits.per_ip("login", 3)])
    async def login() -> dict[str, Any]:
        return {}

    with TestClient(api) as client:
        yield client


class TestPerAddress:
    def test_the_call_past_the_limit_is_429_with_retry_after(
        self, counter: Counter, app: TestClient
    ) -> None:
        codes = [app.post("/login").status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]
        assert app.post("/login").headers["retry-after"] == "42"

    def test_another_address_has_its_own_count(self, counter: Counter, app: TestClient) -> None:
        for _ in range(4):
            app.post("/login")
        counter.counts[("login", "testclient")] = 0
        assert app.post("/login").status_code == 200
        assert set(counter.counts) == {("login", "testclient")}

    def test_a_dead_redis_lets_the_request_through(self, counter: Counter, app: TestClient) -> None:
        counter.down = True
        assert all(app.post("/login").status_code == 200 for _ in range(5))

    def test_switched_off_counts_nothing(
        self, counter: Counter, app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RATE_LIMITS_ENABLED", "false")
        get_settings.cache_clear()
        assert all(app.post("/login").status_code == 200 for _ in range(5))
        assert counter.counts == {}


class TestTheRealApp:
    """The limits are wired on the routes, ahead of anything that touches a store."""

    @pytest.fixture
    def real(self) -> Iterator[TestClient]:
        from mycel.api.app import create_app
        from mycel.api.dependencies import current_user
        from mycel.core.config import Settings
        from mycel.services.auth import Principal

        app = create_app(Settings(otel_enabled=False))
        app.dependency_overrides[current_user] = lambda: Principal(id=1, email="a@example.com")
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client

    @pytest.mark.parametrize(
        ("path", "body", "allowed"),
        [
            ("/auth/login", {"email": "a@example.com", "password": "x" * 8}, 10),
            ("/auth/register", {"email": "a@example.com", "password": "x" * 8}, 5),
            ("/auth/forgot", {"email": "a@example.com"}, 5),
            ("/auth/reset", {"token": "t", "new_password": "x" * 8}, 5),
            ("/chat", {"question": "how?"}, 20),
        ],
    )
    def test_the_call_past_the_limit_is_429(
        self, counter: Counter, real: TestClient, path: str, body: dict[str, Any], allowed: int
    ) -> None:
        real.post(path, json=body)
        (scope_key,) = counter.counts
        counter.counts[scope_key] = allowed  # the limit is already spent
        assert real.post(path, json=body).status_code == 429
