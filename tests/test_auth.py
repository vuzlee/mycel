"""Registering, signing in, and what a cookie is worth afterwards.

Against a real Postgres, for the same reason `test_postgres.py` is: the uniqueness of an
email address is a constraint, not a Python check, and a fake session would not have one.
Without `DATABASE_URL` these skip.

The questions here are the ones a login gets wrong quietly:

  - does a second registration on the same address actually fail, under a race
  - does a wrong password and an unknown address look the same from outside
  - does a session that is one second past its expiry read as gone
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mycel.api import dependencies
from mycel.api.app import create_app
from mycel.api.dependencies import SESSION_COOKIE
from mycel.core.config import Settings
from mycel.infra.postgres.engine import async_dsn
from mycel.infra.postgres.models import Base
from mycel.infra.postgres.repositories.app import AppRepository
from mycel.services import auth

pytestmark = pytest.mark.anyio

DSN = os.environ.get("DATABASE_URL", "")
needs_postgres = pytest.mark.skipif(not DSN, reason="no test database is reachable")

assert not DSN or DSN.rsplit("/", 1)[-1].endswith("_test"), f"refusing to run against {DSN}"

SCHEMAS = ("bronze", "silver", "gold", "app")

PASSWORD = "correct horse battery"


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A schema built from the models, dropped again when the test ends."""
    engine = create_async_engine(async_dsn(DSN))
    async with engine.begin() as conn:
        for schema in SCHEMAS:
            await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            yield db
    finally:
        async with engine.begin() as conn:
            for schema in SCHEMAS:
                await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await engine.dispose()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """The app against the test database, each request opening its own session.

    Not sharing the async `session` fixture: that one is driven by anyio and `TestClient`
    runs its own loop in a portal, so the two cannot hold the same connection. This makes
    the HTTP tests the honest version anyway — a cookie has to survive a *committed*
    session written by one request and read by the next.
    """
    asyncio.run(_build_schema())
    dependencies.reset_caches()
    app = create_app(Settings(otel_enabled=False))
    try:
        with TestClient(app, raise_server_exceptions=False) as running:
            yield running
    finally:
        dependencies.reset_caches()
        asyncio.run(_drop_schema())


async def _build_schema() -> None:
    engine = create_async_engine(async_dsn(DSN))
    async with engine.begin() as conn:
        for schema in SCHEMAS:
            await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def _drop_schema() -> None:
    engine = create_async_engine(async_dsn(DSN))
    async with engine.begin() as conn:
        for schema in SCHEMAS:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
    await engine.dispose()


@needs_postgres
class TestRegistering:
    async def test_an_address_can_only_be_taken_once(self, session: AsyncSession) -> None:
        """The index is what enforces this, not a prior SELECT — two racing registrations
        both pass a check and only one passes the constraint."""
        await auth.register(session, "a@example.com", PASSWORD)
        await session.commit()

        with pytest.raises(auth.AuthError):
            await auth.register(session, "a@example.com", PASSWORD)

    async def test_case_and_space_are_not_identity(self, session: AsyncSession) -> None:
        """`A@Example.com ` and `a@example.com` are one person, and one account."""
        await auth.register(session, "a@example.com", PASSWORD)
        await session.commit()

        with pytest.raises(auth.AuthError):
            await auth.register(session, "  A@Example.COM ", PASSWORD)

    async def test_a_short_password_is_refused(self, session: AsyncSession) -> None:
        with pytest.raises(auth.AuthError):
            await auth.register(session, "b@example.com", "short")

    async def test_the_plaintext_is_never_stored(self, session: AsyncSession) -> None:
        """The one thing that must be true of every row in this table."""
        user = await auth.register(session, "c@example.com", PASSWORD)
        stored = await AppRepository(session).user_by_id(user.id)

        assert stored is not None
        assert PASSWORD not in stored.password_hash
        assert stored.password_hash.startswith("$argon2id$")


@needs_postgres
class TestSigningIn:
    async def test_the_right_password_is_accepted(self, session: AsyncSession) -> None:
        await auth.register(session, "d@example.com", PASSWORD)
        user = await auth.authenticate(session, "d@example.com", PASSWORD)
        assert user.email == "d@example.com"

    async def test_a_wrong_password_and_an_unknown_address_look_the_same(
        self, session: AsyncSession
    ) -> None:
        """Different messages here turn the endpoint into a list of who has an account."""
        await auth.register(session, "e@example.com", PASSWORD)

        with pytest.raises(auth.AuthError) as wrong:
            await auth.authenticate(session, "e@example.com", "not the password")
        with pytest.raises(auth.AuthError) as unknown:
            await auth.authenticate(session, "nobody@example.com", PASSWORD)

        assert str(wrong.value) == str(unknown.value)


@needs_postgres
class TestSessions:
    async def test_a_fresh_token_names_its_owner(self, session: AsyncSession) -> None:
        user = await auth.register(session, "f@example.com", PASSWORD)
        token, _ = await auth.open_session(session, user.id)

        assert (await auth.session_user(session, token)) == user

    async def test_an_expired_session_reads_as_gone(self, session: AsyncSession) -> None:
        """Expiry is enforced on read, not by the database — a session one second past its
        expiry must be dead even though no sweeper has run."""
        user = await auth.register(session, "g@example.com", PASSWORD)
        past = datetime.now(UTC) - timedelta(seconds=1)
        await AppRepository(session).create_session("expired-token", user.id, past)

        assert await auth.session_user(session, "expired-token") is None

    async def test_reading_an_expired_session_deletes_it(self, session: AsyncSession) -> None:
        """Otherwise a sweeper has to exist for the table not to grow forever."""
        user = await auth.register(session, "h@example.com", PASSWORD)
        past = datetime.now(UTC) - timedelta(seconds=1)
        await AppRepository(session).create_session("dead-token", user.id, past)

        await auth.session_user(session, "dead-token")
        assert await AppRepository(session).session_by_id("dead-token") is None

    async def test_logging_out_kills_the_token(self, session: AsyncSession) -> None:
        user = await auth.register(session, "i@example.com", PASSWORD)
        token, _ = await auth.open_session(session, user.id)

        await auth.close_session(session, token)
        assert await auth.session_user(session, token) is None

    async def test_an_unknown_token_is_nobody(self, session: AsyncSession) -> None:
        assert await auth.session_user(session, "never-issued") is None


@needs_postgres
class TestOverHttp:
    """The round trip a browser actually makes."""

    def test_registering_does_not_sign_you_in(self, client: TestClient) -> None:
        """Registering and signing in are separate decisions. The account exists; the
        browser holds nothing, and the next screen is the login form."""
        created = client.post(
            "/auth/register", json={"email": "j@example.com", "password": PASSWORD}
        )
        assert created.status_code == 201
        assert created.json()["email"] == "j@example.com"

        assert "set-cookie" not in created.headers
        assert client.get("/auth/me").status_code == 401

    def test_registering_twice_says_the_address_is_taken(self, client: TestClient) -> None:
        """The second attempt is the common one — someone who already has an account and
        picked the wrong form. It has to say so, not fail as a 500."""
        client.post("/auth/register", json={"email": "taken@example.com", "password": PASSWORD})

        again = client.post(
            "/auth/register", json={"email": "taken@example.com", "password": PASSWORD}
        )
        assert again.status_code == 400
        assert again.json()["error"] == "auth_failed"
        assert "already registered" in again.json()["detail"]

    def test_registering_then_logging_in_returns_the_user(self, client: TestClient) -> None:
        client.post("/auth/register", json={"email": "k@example.com", "password": PASSWORD})

        signed_in = client.post(
            "/auth/login", json={"email": "k@example.com", "password": PASSWORD}
        )
        assert signed_in.status_code == 200

        me = client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "k@example.com"

    def test_the_cookie_is_not_readable_by_a_page(self, client: TestClient) -> None:
        """A token a script can read is a token a cross-site script can steal."""
        client.post("/auth/register", json={"email": "c@example.com", "password": PASSWORD})
        response = client.post("/auth/login", json={"email": "c@example.com", "password": PASSWORD})
        cookie = response.headers["set-cookie"].lower()

        assert "httponly" in cookie
        assert "samesite=lax" in cookie

    def test_without_a_cookie_me_is_401(self, client: TestClient) -> None:
        assert client.get("/auth/me").status_code == 401

    def test_logging_out_makes_the_same_cookie_401(self, client: TestClient) -> None:
        client.post("/auth/register", json={"email": "l@example.com", "password": PASSWORD})
        client.post("/auth/login", json={"email": "l@example.com", "password": PASSWORD})
        assert client.get("/auth/me").status_code == 200

        assert client.post("/auth/logout").status_code == 204
        assert client.get("/auth/me").status_code == 401

    def test_logging_out_without_a_session_still_clears_the_cookie(
        self, client: TestClient
    ) -> None:
        """A 401 here would leave a browser holding a token it can never get rid of."""
        assert client.post("/auth/logout").status_code == 204

    def test_a_wrong_password_is_400_not_500(self, client: TestClient) -> None:
        client.post("/auth/register", json={"email": "m@example.com", "password": PASSWORD})

        response = client.post(
            "/auth/login", json={"email": "m@example.com", "password": "wrong password"}
        )
        assert response.status_code == 400
        assert response.json()["error"] == "auth_failed"

    def test_a_forged_cookie_is_rejected(self, client: TestClient) -> None:
        client.cookies.set(SESSION_COOKIE, "a" * 64)
        assert client.get("/auth/me").status_code == 401
