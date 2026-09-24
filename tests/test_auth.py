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
from mycel.core.config import Settings, get_settings
from mycel.infra.postgres.engine import async_dsn, get_engine
from mycel.infra.postgres.models import Base
from mycel.infra.postgres.repositories.app import AppRepository
from mycel.services import auth, permission

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
    # `TestClient` runs its own event loop, and the cached engine may hold connections
    # opened on an anyio loop that has since closed — every query on one then fails as an
    # internal error that looks nothing like its cause.
    get_engine.cache_clear()
    app = create_app(Settings(otel_enabled=False))
    try:
        with TestClient(app, raise_server_exceptions=False) as running:
            yield running
    finally:
        dependencies.reset_caches()
        get_engine.cache_clear()
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


@needs_postgres
class TestChangingPassword:
    """The old password is required even though the caller already holds a live cookie."""

    async def test_the_new_password_works_and_the_old_one_does_not(
        self, session: AsyncSession
    ) -> None:
        user = await auth.register(session, "pw@example.com", PASSWORD)

        await auth.change_password(session, user.id, PASSWORD, "a longer new one")

        assert await auth.authenticate(session, "pw@example.com", "a longer new one") == user
        with pytest.raises(auth.AuthError):
            await auth.authenticate(session, "pw@example.com", PASSWORD)

    async def test_a_wrong_current_password_changes_nothing(self, session: AsyncSession) -> None:
        user = await auth.register(session, "pw2@example.com", PASSWORD)

        with pytest.raises(auth.AuthError):
            await auth.change_password(session, user.id, "not it", "a longer new one")
        assert await auth.authenticate(session, "pw2@example.com", PASSWORD) == user

    async def test_a_short_new_password_is_refused(self, session: AsyncSession) -> None:
        user = await auth.register(session, "pw3@example.com", PASSWORD)

        with pytest.raises(auth.AuthError):
            await auth.change_password(session, user.id, PASSWORD, "short")

    async def test_other_sessions_end_and_the_named_one_survives(
        self, session: AsyncSession
    ) -> None:
        """The point of changing a password is that someone else may know the old one — a
        session already open does not care what the password is now."""
        user = await auth.register(session, "pw4@example.com", PASSWORD)
        mine, _ = await auth.open_session(session, user.id)
        theirs, _ = await auth.open_session(session, user.id)

        ended = await auth.change_password(
            session, user.id, PASSWORD, "a longer new one", keep_token=mine
        )

        assert ended == 1
        assert await auth.session_user(session, mine) == user
        assert await auth.session_user(session, theirs) is None

    def test_over_http_the_tab_doing_it_stays_signed_in(self, client: TestClient) -> None:
        client.post("/auth/register", json={"email": "pw5@example.com", "password": PASSWORD})
        client.post("/auth/login", json={"email": "pw5@example.com", "password": PASSWORD})

        changed = client.post(
            "/auth/password",
            json={"current_password": PASSWORD, "new_password": "a longer new one"},
        )

        assert changed.status_code == 204
        assert client.get("/auth/me").status_code == 200

    def test_over_http_without_a_cookie_it_is_401(self, client: TestClient) -> None:
        response = client.post(
            "/auth/password",
            json={"current_password": PASSWORD, "new_password": "a longer new one"},
        )
        assert response.status_code == 401


@needs_postgres
class TestSweepingSessions:
    async def test_only_expired_rows_go(self, session: AsyncSession) -> None:
        user = await auth.register(session, "sw@example.com", PASSWORD)
        live, _ = await auth.open_session(session, user.id)
        past = datetime.now(UTC) - timedelta(seconds=1)
        await AppRepository(session).create_session("stale", user.id, past)

        assert await auth.sweep_expired_sessions(session) == 1
        assert await auth.session_user(session, live) == user


@needs_postgres
class TestWhoMayRegister:
    """Open registration is right for one machine on localhost and wrong past it."""

    async def test_an_invite_code_is_required_when_one_is_set(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRATION_INVITE_CODE", "let-me-in")
        get_settings.cache_clear()

        with pytest.raises(auth.AuthError):
            await auth.register(session, "n@example.com", PASSWORD)

        user = await auth.register(session, "n@example.com", PASSWORD, "let-me-in")
        assert user.email == "n@example.com"

    async def test_a_domain_outside_the_allowlist_is_refused(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRATION_ALLOWED_DOMAINS", "example.com")
        get_settings.cache_clear()

        with pytest.raises(auth.AuthError):
            await auth.register(session, "o@elsewhere.org", PASSWORD)
        assert (await auth.register(session, "o@example.com", PASSWORD)).id

    async def test_both_refusals_read_the_same(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two messages would tell someone with neither which half to guess."""
        monkeypatch.setenv("REGISTRATION_INVITE_CODE", "let-me-in")
        monkeypatch.setenv("REGISTRATION_ALLOWED_DOMAINS", "example.com")
        get_settings.cache_clear()

        with pytest.raises(auth.AuthError) as bad_code:
            await auth.register(session, "p@example.com", PASSWORD, "wrong")
        with pytest.raises(auth.AuthError) as bad_domain:
            await auth.register(session, "p@elsewhere.org", PASSWORD, "let-me-in")

        assert str(bad_code.value) == str(bad_domain.value)


@needs_postgres
class TestMembership:
    """A row is a grant. No row, no access — the absent case is the closed one."""

    async def test_a_new_account_may_read_nothing(self, session: AsyncSession) -> None:
        """Otherwise a person nobody has recorded anything about is an administrator."""
        user = await auth.register(session, "mem@example.com", PASSWORD)

        assert await permission.readable_projects(user) == frozenset()
        assert await permission.can_read_project(user, "MYC") is False

    async def test_a_grant_is_what_opens_one_project(self, session: AsyncSession) -> None:
        user = await auth.register(session, "mem2@example.com", PASSWORD)

        await permission.grant(session, user.id, "MYC")

        assert await AppRepository(session).projects_for(user.id) == frozenset({"MYC"})

    async def test_granting_twice_is_not_an_error(self, session: AsyncSession) -> None:
        user = await auth.register(session, "mem3@example.com", PASSWORD)

        await permission.grant(session, user.id, "MYC")
        await permission.grant(session, user.id, "MYC")

        assert await AppRepository(session).projects_for(user.id) == frozenset({"MYC"})

    async def test_revoking_leaves_the_others(self, session: AsyncSession) -> None:
        user = await auth.register(session, "mem4@example.com", PASSWORD)
        await permission.grant(session, user.id, "MYC")
        await permission.grant(session, user.id, "OPS")

        await permission.revoke(session, user.id, "MYC")

        assert await AppRepository(session).projects_for(user.id) == frozenset({"OPS"})

    async def test_revoking_what_was_never_granted_is_not_an_error(
        self, session: AsyncSession
    ) -> None:
        user = await auth.register(session, "mem5@example.com", PASSWORD)

        await permission.revoke(session, user.id, "MYC")

        assert await AppRepository(session).projects_for(user.id) == frozenset()

    async def test_one_person_s_grant_is_not_another_s(self, session: AsyncSession) -> None:
        one = await auth.register(session, "mem6@example.com", PASSWORD)
        two = await auth.register(session, "mem7@example.com", PASSWORD)
        await permission.grant(session, one.id, "MYC")

        assert await AppRepository(session).projects_for(two.id) == frozenset()


@needs_postgres
class TestForgottenPasswords:
    """A one-shot token, mailed to the address on the account. The token is never stored —
    only a hash of it, because a link is a password for as long as it lives."""

    @pytest.fixture
    def outbox(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
        """Every message the code tried to send, instead of an SMTP connection."""
        sent: list[tuple[str, str, str]] = []

        async def capture(to: str, subject: str, body: str) -> None:
            sent.append((to, subject, body))

        monkeypatch.setattr(auth.mail, "send", capture)
        return sent

    @staticmethod
    def _token(body: str) -> str:
        return body.split("token=", 1)[1].split()[0]

    async def test_the_link_sets_a_new_password(
        self, session: AsyncSession, outbox: list[tuple[str, str, str]]
    ) -> None:
        user = await auth.register(session, "forgot@example.com", PASSWORD)

        await auth.begin_password_reset(session, "forgot@example.com")
        await auth.reset_password(session, self._token(outbox[0][2]), "a longer new one")

        assert await auth.authenticate(session, "forgot@example.com", "a longer new one") == user

    async def test_an_unknown_address_sends_nothing_and_says_nothing(
        self, session: AsyncSession, outbox: list[tuple[str, str, str]]
    ) -> None:
        """Answering differently would turn this into a list of who has an account."""
        await auth.begin_password_reset(session, "nobody@example.com")

        assert outbox == []

    async def test_a_link_works_once(
        self, session: AsyncSession, outbox: list[tuple[str, str, str]]
    ) -> None:
        await auth.register(session, "once@example.com", PASSWORD)
        await auth.begin_password_reset(session, "once@example.com")
        token = self._token(outbox[0][2])

        await auth.reset_password(session, token, "a longer new one")

        with pytest.raises(auth.AuthError):
            await auth.reset_password(session, token, "another one entirely")

    async def test_an_expired_link_is_refused(
        self,
        session: AsyncSession,
        outbox: list[tuple[str, str, str]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("PASSWORD_RESET_TTL_SECONDS", "-1")
        get_settings.cache_clear()
        await auth.register(session, "stale@example.com", PASSWORD)
        await auth.begin_password_reset(session, "stale@example.com")

        with pytest.raises(auth.AuthError):
            await auth.reset_password(session, self._token(outbox[0][2]), "a longer new one")
        get_settings.cache_clear()

    async def test_a_made_up_token_is_refused(self, session: AsyncSession) -> None:
        with pytest.raises(auth.AuthError):
            await auth.reset_password(session, "not a real token", "a longer new one")

    async def test_a_short_new_password_is_refused_before_the_link_is_spent(
        self, session: AsyncSession, outbox: list[tuple[str, str, str]]
    ) -> None:
        """Refusing after spending it would cost the link for a typo."""
        await auth.register(session, "shortpw@example.com", PASSWORD)
        await auth.begin_password_reset(session, "shortpw@example.com")
        token = self._token(outbox[0][2])

        with pytest.raises(auth.AuthError):
            await auth.reset_password(session, token, "short")
        await auth.reset_password(session, token, "a longer new one")

    async def test_every_session_ends_including_the_one_asking(
        self, session: AsyncSession, outbox: list[tuple[str, str, str]]
    ) -> None:
        """A person resetting does not know which browsers are still open, and the reason
        to reset is that one of them may not be theirs."""
        user = await auth.register(session, "sessions@example.com", PASSWORD)
        await auth.open_session(session, user.id)
        await auth.open_session(session, user.id)
        await auth.begin_password_reset(session, "sessions@example.com")

        ended = await auth.reset_password(session, self._token(outbox[0][2]), "a longer new one")

        assert ended == 2


@needs_postgres
class TestMembersOf:
    """The read behind the project-access screen."""

    async def test_it_lists_everyone_granted_by_address(self, session: AsyncSession) -> None:
        one = await auth.register(session, "am@example.com", PASSWORD)
        two = await auth.register(session, "bm@example.com", PASSWORD)
        await auth.register(session, "cm@example.com", PASSWORD)
        await permission.grant(session, one.id, "MYC")
        await permission.grant(session, two.id, "MYC")

        members = await AppRepository(session).members_of("MYC")

        assert [m.email for m in members] == ["am@example.com", "bm@example.com"]

    async def test_a_project_nobody_has_is_empty(self, session: AsyncSession) -> None:
        assert await AppRepository(session).members_of("NONE") == []


@needs_postgres
class TestProjectAccessOverHttp:
    """The screen that replaced opening a shell. You may grant what you may read."""

    @staticmethod
    def _sign_in(client: TestClient, email: str) -> None:
        created = client.post("/auth/register", json={"email": email, "password": PASSWORD})
        assert created.status_code == 201, created.text
        entered = client.post("/auth/login", json={"email": email, "password": PASSWORD})
        assert entered.status_code == 200, entered.text

    @staticmethod
    def _grant(email: str, project: str) -> None:
        """Straight to the database: somebody has to be first, and until migration 0007
        has run on a real deployment that somebody is whoever runs this."""

        async def work() -> None:
            engine = create_async_engine(async_dsn(DSN))
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                user = await AppRepository(db).user_by_email(email)
                assert user is not None
                await permission.grant(db, user.id, project)
                await db.commit()
            await engine.dispose()

        asyncio.run(work())

    def test_a_project_you_cannot_read_has_no_member_list(self, client: TestClient) -> None:
        """404 rather than 403: someone who cannot read a project should not learn it
        exists."""
        self._sign_in(client, "outsider@example.com")

        assert client.get("/projects/MYC/members").status_code == 404

    def test_granting_lets_the_other_person_read_it(self, client: TestClient) -> None:
        self._sign_in(client, "owner@example.com")
        self._grant("owner@example.com", "MYC")
        client.post("/auth/register", json={"email": "invited@example.com", "password": PASSWORD})

        assert client.put("/projects/MYC/members/invited@example.com").status_code == 204

        listed = client.get("/projects/MYC/members").json()
        assert [m["email"] for m in listed] == ["invited@example.com", "owner@example.com"]

    def test_granting_twice_is_the_same_end_state(self, client: TestClient) -> None:
        self._sign_in(client, "owner2@example.com")
        self._grant("owner2@example.com", "MYC")
        client.post("/auth/register", json={"email": "twice@example.com", "password": PASSWORD})

        client.put("/projects/MYC/members/twice@example.com")
        assert client.put("/projects/MYC/members/twice@example.com").status_code == 204
        assert len(client.get("/projects/MYC/members").json()) == 2

    def test_revoking_takes_it_back(self, client: TestClient) -> None:
        self._sign_in(client, "owner3@example.com")
        self._grant("owner3@example.com", "MYC")
        client.post("/auth/register", json={"email": "gone@example.com", "password": PASSWORD})
        client.put("/projects/MYC/members/gone@example.com")

        assert client.delete("/projects/MYC/members/gone@example.com").status_code == 204
        assert [m["email"] for m in client.get("/projects/MYC/members").json()] == [
            "owner3@example.com"
        ]

    def test_an_address_with_no_account_cannot_be_granted(self, client: TestClient) -> None:
        """An account that exists before its owner does is an account nobody controls."""
        self._sign_in(client, "owner4@example.com")
        self._grant("owner4@example.com", "MYC")

        assert client.put("/projects/MYC/members/stranger@example.com").status_code == 404

    def test_signed_out_gets_nothing(self, client: TestClient) -> None:
        assert client.get("/projects/MYC/members").status_code == 401


@needs_postgres
class TestForgottenPasswordOverHttp:
    def test_it_refuses_when_the_deployment_cannot_send_mail(self, client: TestClient) -> None:
        """A link that is never sent is worse than a feature that says it is off."""
        response = client.post("/auth/forgot", json={"email": "who@example.com"})

        assert response.status_code == 503

    def test_an_unknown_address_is_accepted_like_any_other(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("mycel.notify.mail.configured", lambda: True)

        assert client.post("/auth/forgot", json={"email": "nobody@example.com"}).status_code == 202

    def test_a_bad_token_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/auth/reset", json={"token": "made up", "new_password": "a longer new one"}
        )

        assert response.status_code == 400
