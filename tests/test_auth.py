"""Signing in with Google or an emailed code, and what a cookie is worth afterwards."""

import asyncio
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from mycel.api.app import create_app
from mycel.api.dependencies import SESSION_COOKIE
from mycel.core.config import Settings, get_settings
from mycel.infra import smtp
from mycel.infra.postgres.engine import async_dsn, get_engine
from mycel.infra.postgres.models import Base
from mycel.infra.postgres.repositories.accounts import AccountRepository
from mycel.infra.postgres.repositories.identity import IdentityRepository
from mycel.services import auth, google_signin, oauth, permission, signin_code
from tests.fakes import DSN, SCHEMAS, needs_postgres

pytestmark = pytest.mark.anyio

CLIENT_ID = "client-id.apps.googleusercontent.com"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class CodeRedis:
    """Enough Redis for a code: get, set, incr, expire, getdel, delete, a pipeline."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self.values.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> bool:
        self.values[key] = value
        return True

    async def incr(self, key: str) -> int:
        self.values[key] = int(self.values.get(key, 0)) + 1
        return int(self.values[key])

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def getdel(self, key: str) -> Any:
        return self.values.pop(key, None)

    async def delete(self, *keys: str) -> int:
        return sum(self.values.pop(k, None) is not None for k in keys)

    def pipeline(self) -> "CodeRedis.Pipe":
        return CodeRedis.Pipe(self)

    class Pipe:
        def __init__(self, owner: "CodeRedis") -> None:
            self.owner = owner
            self.calls: list[Any] = []

        def set(self, *args: Any, **kwargs: Any) -> None:
            self.calls.append(self.owner.set(*args, **kwargs))

        def delete(self, *keys: str) -> None:
            self.calls.append(self.owner.delete(*keys))

        async def execute(self) -> list[Any]:
            return [await c for c in self.calls]


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> CodeRedis:
    fake = CodeRedis()

    async def _get_client() -> CodeRedis:
        return fake

    monkeypatch.setattr(signin_code, "get_client", _get_client)
    monkeypatch.setattr(google_signin, "get_client", _get_client)
    return fake


@pytest.fixture
def mailbox(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Mail as a list; `smtp.configured()` is true while it is in use."""
    sent: list[tuple[str, str]] = []

    async def send(to: str, subject: str, body: str) -> None:
        sent.append((to, body))

    monkeypatch.setattr(smtp, "configured", lambda settings=None: True)
    monkeypatch.setattr(smtp, "send", send)
    return sent


@pytest.fixture
def google(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Google as a client id, a token endpoint and a key: `claims` is what the next token says."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://mycel.example.com")
    get_settings.cache_clear()
    state: dict[str, Any] = {"claims": {}}

    async def post_token(url: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        return 200, {"id_token": id_token(state["claims"])}

    monkeypatch.setattr(oauth, "post_token", post_token)
    monkeypatch.setattr(google_signin, "signing_key", lambda token: _KEY.public_key())
    return state


def id_token(claims: dict[str, Any], key: Any = _KEY) -> str:
    now = int(time.time())
    body = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "iat": now,
        "exp": now + 300,
        "sub": "g-1",
        "email": "ann@example.com",
        "email_verified": True,
        **claims,
    }
    return jwt.encode(body, key, algorithm="RS256")


@pytest.fixture
def client() -> Iterator[TestClient]:
    """The app against the test database, each request opening its own session."""
    asyncio.run(_build_schema())
    # `TestClient` runs its own loop; cached engine connections from a closed loop would fail.
    get_engine.cache_clear()
    app = create_app(Settings(otel_enabled=False))
    try:
        with TestClient(app, raise_server_exceptions=False) as running:
            yield running
    finally:
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
class TestTheAccountBehindASignIn:
    async def test_the_first_sign_in_makes_the_account(self, session: AsyncSession) -> None:
        user = await auth.account_for(session, "New@Example.com ")

        assert user.email == "new@example.com"

    async def test_the_same_address_is_the_same_account(self, session: AsyncSession) -> None:
        first = await auth.account_for(session, "same@example.com")

        assert await auth.account_for(session, "SAME@example.com") == first

    async def test_google_links_to_an_account_made_with_a_code(self, session: AsyncSession) -> None:
        """Someone who came in by mail keeps their history once they use Google."""
        by_code = await auth.account_for(session, "link@example.com")

        by_google = await auth.account_for(session, "link@example.com", "g-link")

        assert by_google == by_code
        found = await IdentityRepository(session).user_by_google_sub("g-link")
        assert found is not None and found.id == by_code.id

    async def test_the_google_id_wins_over_a_changed_address(self, session: AsyncSession) -> None:
        """Google lets people rename their address; the account follows the id."""
        first = await auth.account_for(session, "old@example.com", "g-moved")

        assert await auth.account_for(session, "new-name@example.com", "g-moved") == first

    async def test_a_domain_outside_the_allowlist_gets_no_account(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRATION_ALLOWED_DOMAINS", "example.com")
        get_settings.cache_clear()

        with pytest.raises(auth.AuthError):
            await auth.account_for(session, "o@elsewhere.org")
        assert (await auth.account_for(session, "o@example.com")).id

    async def test_removing_a_domain_locks_its_existing_accounts_out(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An account made while the domain was allowed must not outlive the allowlist."""
        await auth.account_for(session, "o@elsewhere.org", "g-old")
        monkeypatch.setenv("REGISTRATION_ALLOWED_DOMAINS", "example.com")
        get_settings.cache_clear()

        with pytest.raises(auth.AuthError):
            await auth.account_for(session, "o@elsewhere.org", "g-old")
        with pytest.raises(auth.AuthError):
            await auth.account_for(session, "o@elsewhere.org")


class TestTheEmailedCode:
    async def test_the_right_code_works_once(self, redis: CodeRedis) -> None:
        code = await signin_code.issue("ann@example.com")
        assert code is not None and len(code) == signin_code.DIGITS

        assert await signin_code.spend("ANN@example.com", code) == "ann@example.com"
        with pytest.raises(auth.AuthError):
            await signin_code.spend("ann@example.com", code)

    async def test_a_wrong_code_is_refused(self, redis: CodeRedis) -> None:
        code = await signin_code.issue("ann@example.com")
        assert code is not None
        wrong = "000000" if code != "000000" else "111111"

        with pytest.raises(auth.AuthError):
            await signin_code.spend("ann@example.com", wrong)
        assert await signin_code.spend("ann@example.com", code) == "ann@example.com"

    async def test_five_wrong_guesses_burn_the_code(self, redis: CodeRedis) -> None:
        """Without a cap, a million codes is a million requests away."""
        code = await signin_code.issue("ann@example.com")
        assert code is not None
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(signin_code.MAX_TRIES):
            with pytest.raises(auth.AuthError):
                await signin_code.spend("ann@example.com", wrong)

        with pytest.raises(auth.AuthError):
            await signin_code.spend("ann@example.com", code)

    async def test_a_new_code_replaces_the_old_one(self, redis: CodeRedis) -> None:
        old = await signin_code.issue("ann@example.com")
        new = await signin_code.issue("ann@example.com")
        assert old is not None and new is not None

        if old != new:
            with pytest.raises(auth.AuthError):
                await signin_code.spend("ann@example.com", old)
        assert await signin_code.spend("ann@example.com", new) == "ann@example.com"

    async def test_nothing_is_stored_in_the_clear(self, redis: CodeRedis) -> None:
        code = await signin_code.issue("ann@example.com")

        assert code not in [str(v) for v in redis.values.values()]

    async def test_an_address_outside_the_allowlist_gets_no_code(
        self, redis: CodeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRATION_ALLOWED_DOMAINS", "example.com")
        get_settings.cache_clear()

        assert await signin_code.issue("o@elsewhere.org") is None


class TestTheGoogleToken:
    def test_a_good_token_reads(self, google: dict[str, Any]) -> None:
        claims = google_signin.verify(id_token({}), CLIENT_ID)

        assert claims["email"] == "ann@example.com"

    def test_another_key_is_refused(self, google: dict[str, Any]) -> None:
        stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        with pytest.raises(google_signin.SignInError):
            google_signin.verify(id_token({}, stranger), CLIENT_ID)

    def test_a_token_for_another_app_is_refused(self, google: dict[str, Any]) -> None:
        with pytest.raises(google_signin.SignInError):
            google_signin.verify(id_token({"aud": "someone-else"}), CLIENT_ID)

    def test_an_expired_token_is_refused(self, google: dict[str, Any]) -> None:
        with pytest.raises(google_signin.SignInError):
            google_signin.verify(id_token({"exp": int(time.time()) - 60}), CLIENT_ID)

    def test_another_issuer_is_refused(self, google: dict[str, Any]) -> None:
        with pytest.raises(google_signin.SignInError):
            google_signin.verify(id_token({"iss": "https://evil.example"}), CLIENT_ID)


class TestTheGoogleRound:
    async def test_a_hint_goes_straight_to_that_account(
        self, google: dict[str, Any], redis: CodeRedis
    ) -> None:
        url, _ = await google_signin.start("ann@example.com", None)
        query = parse_qs(urlsplit(url).query)

        assert query["login_hint"] == ["ann@example.com"]
        assert query["scope"] == ["openid email"]
        assert "prompt" not in query
        assert query["redirect_uri"] == ["https://mycel.example.com/auth/google/callback"]

    async def test_no_hint_shows_the_chooser(
        self, google: dict[str, Any], redis: CodeRedis
    ) -> None:
        url, _ = await google_signin.start(None, None)

        assert parse_qs(urlsplit(url).query)["prompt"] == ["select_account"]

    async def test_the_round_finishes_once(self, google: dict[str, Any], redis: CodeRedis) -> None:
        url, state = await google_signin.start(None, "/app/knowledge")
        google["claims"] = {"nonce": parse_qs(urlsplit(url).query)["nonce"][0]}

        who = await google_signin.finish(state, state, "code")

        assert (who.sub, who.email, who.next) == ("g-1", "ann@example.com", "/app/knowledge")
        with pytest.raises(google_signin.SignInError):
            await google_signin.finish(state, state, "code")

    async def test_another_browser_cannot_finish_it(
        self, google: dict[str, Any], redis: CodeRedis
    ) -> None:
        """Login CSRF: my callback link opened in your browser signs you into me."""
        _, state = await google_signin.start(None, None)

        with pytest.raises(google_signin.SignInError):
            await google_signin.finish(state, None, "code")

    async def test_a_token_from_another_round_is_refused(
        self, google: dict[str, Any], redis: CodeRedis
    ) -> None:
        _, state = await google_signin.start(None, None)
        google["claims"] = {"nonce": "from-somewhere-else"}

        with pytest.raises(google_signin.SignInError):
            await google_signin.finish(state, state, "code")

    async def test_an_unverified_address_is_refused(
        self, google: dict[str, Any], redis: CodeRedis
    ) -> None:
        """Linking by an address Google has not checked hands an account to whoever typed it."""
        url, state = await google_signin.start(None, None)
        nonce = parse_qs(urlsplit(url).query)["nonce"][0]
        google["claims"] = {"nonce": nonce, "email_verified": False}

        with pytest.raises(google_signin.SignInError):
            await google_signin.finish(state, state, "code")

    @pytest.mark.parametrize(
        ("asked", "lands"),
        [
            ("/app/knowledge", "/app/knowledge"),
            ("https://evil.example/", "/app/"),
            ("//evil.example/app/", "/app/"),
            ("/app//evil.example", "/app/"),
            (None, "/app/"),
        ],
    )
    def test_next_stays_inside_the_app(self, asked: str | None, lands: str) -> None:
        assert google_signin.safe_next(asked) == lands


@needs_postgres
class TestOverHttp:
    """The round trip a browser actually makes."""

    @staticmethod
    def sign_in(client: TestClient, email: str = "k@example.com") -> None:
        code = asyncio.run(signin_code.issue(email))
        assert code is not None
        signed_in = client.post("/auth/code/verify", json={"email": email, "code": code})
        assert signed_in.status_code == 200, signed_in.text

    def test_a_code_signs_you_in(self, client: TestClient, redis: CodeRedis) -> None:
        self.sign_in(client)

        me = client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "k@example.com"

    def test_loading_the_app_extends_the_cookie(self, client: TestClient, redis: CodeRedis) -> None:
        """The browser drops a cookie at its max-age; each page load sets it again."""
        self.sign_in(client)

        cookie = client.get("/auth/me").headers.get("set-cookie", "")
        assert "mycel_session=" in cookie and "Max-Age=1209600" in cookie

    def test_asking_for_a_code_mails_it(
        self, client: TestClient, redis: CodeRedis, mailbox: list[tuple[str, str]]
    ) -> None:
        assert client.post("/auth/code", json={"email": "m@example.com"}).status_code == 202

        assert [to for to, _ in mailbox] == ["m@example.com"]

    def test_no_mail_server_is_503(self, client: TestClient) -> None:
        response = client.post("/auth/code", json={"email": "m@example.com"})

        assert response.status_code == 503

    def test_a_wrong_code_is_400_not_500(self, client: TestClient, redis: CodeRedis) -> None:
        asyncio.run(signin_code.issue("w@example.com"))

        response = client.post(
            "/auth/code/verify", json={"email": "w@example.com", "code": "x" * 6}
        )

        assert response.status_code == 400
        assert response.json()["error"] == "auth_failed"

    def test_the_cookie_is_not_readable_by_a_page(
        self, client: TestClient, redis: CodeRedis
    ) -> None:
        """A token a script can read is a token a cross-site script can steal."""
        code = asyncio.run(signin_code.issue("c@example.com"))
        response = client.post("/auth/code/verify", json={"email": "c@example.com", "code": code})
        cookie = response.headers["set-cookie"].lower()

        assert "httponly" in cookie
        assert "samesite=lax" in cookie

    def test_without_a_cookie_me_is_401(self, client: TestClient) -> None:
        assert client.get("/auth/me").status_code == 401

    def test_logging_out_makes_the_same_cookie_401(
        self, client: TestClient, redis: CodeRedis
    ) -> None:
        self.sign_in(client, "l@example.com")
        assert client.get("/auth/me").status_code == 200

        assert client.post("/auth/logout").status_code == 204
        assert client.get("/auth/me").status_code == 401

    def test_logging_out_without_a_session_still_clears_the_cookie(
        self, client: TestClient
    ) -> None:
        """A 401 here would leave a browser holding a token it can never get rid of."""
        assert client.post("/auth/logout").status_code == 204

    def test_a_forged_cookie_is_rejected(self, client: TestClient) -> None:
        client.cookies.set(SESSION_COOKIE, "a" * 64)
        assert client.get("/auth/me").status_code == 401

    def test_the_page_learns_which_ways_in_there_are(self, client: TestClient) -> None:
        assert client.get("/auth/methods").json() == {"google": False, "code": False}

    def test_google_sign_in_end_to_end(
        self, client: TestClient, google: dict[str, Any], redis: CodeRedis
    ) -> None:
        started = client.get(
            "/auth/google/signin", params={"next": "/app/knowledge"}, follow_redirects=False
        )
        assert started.status_code == 307
        query = parse_qs(urlsplit(started.headers["location"]).query)
        google["claims"] = {"nonce": query["nonce"][0], "sub": "g-e2e", "email": "e2e@example.com"}

        back = client.get(
            "/auth/google/callback",
            params={"code": "c", "state": query["state"][0]},
            follow_redirects=False,
        )

        assert back.status_code == 307
        assert back.headers["location"] == "https://mycel.example.com/app/knowledge"
        assert client.get("/auth/me").json()["email"] == "e2e@example.com"

    def test_a_cancelled_google_sign_in_comes_back_to_login(self, client: TestClient) -> None:
        response = client.get(
            "/auth/google/callback",
            # Google sends the state back with the error, so the round is still a sign-in.
            params={"error": "access_denied", "state": "signin.abc"},
            follow_redirects=False,
        )

        assert response.status_code == 307
        assert response.headers["location"].endswith("/app/login?error=access_denied")

    def test_a_callback_from_another_browser_signs_nobody_in(
        self, client: TestClient, google: dict[str, Any], redis: CodeRedis
    ) -> None:
        started = client.get("/auth/google/signin", follow_redirects=False)
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
        client.cookies.clear()

        back = client.get(
            "/auth/google/callback",
            params={"code": "c", "state": state},
            follow_redirects=False,
        )

        assert back.headers["location"].endswith("/app/login?error=refused")
        assert client.get("/auth/me").status_code == 401

    def test_google_off_is_503(self, client: TestClient) -> None:
        assert client.get("/auth/google/signin", follow_redirects=False).status_code == 503


@needs_postgres
class TestSessions:
    async def test_a_fresh_token_names_its_owner(self, session: AsyncSession) -> None:
        user = await auth.account_for(session, "f@example.com")
        token = await auth.open_session(session, user.id)

        assert (await auth.session_user(session, token)) == user

    async def test_a_busy_session_is_written_at_most_once_a_minute(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every poll was an UPDATE; last_seen only needs minute precision."""
        user = await auth.account_for(session, "busy@example.com")
        token = await auth.open_session(session, user.id)
        touched: list[str] = []

        async def touch(self: Any, token: str, at: Any) -> None:
            touched.append(token)

        monkeypatch.setattr(IdentityRepository, "touch_session", touch)
        for _ in range(3):
            assert await auth.session_user(session, token) == user

        assert touched == []

    async def test_a_session_in_use_does_not_expire(self, session: AsyncSession) -> None:
        """Using it pushes the end out again; only 14 idle days end it."""
        user = await auth.account_for(session, "active@example.com")
        soon = datetime.now(UTC) + timedelta(hours=1)
        await IdentityRepository(session).create_session("active-token", user.id, soon)
        long_ago = datetime.now(UTC) - timedelta(days=1)
        await IdentityRepository(session).touch_session("active-token", long_ago)

        assert await auth.session_user(session, "active-token") == user
        row = await IdentityRepository(session).session_by_id("active-token")
        assert row is not None and row.expires_at > datetime.now(UTC) + timedelta(days=13)

    async def test_an_expired_session_reads_as_gone(self, session: AsyncSession) -> None:
        """Expiry is enforced on read, not by the database."""
        user = await auth.account_for(session, "g@example.com")
        past = datetime.now(UTC) - timedelta(seconds=1)
        await IdentityRepository(session).create_session("expired-token", user.id, past)

        assert await auth.session_user(session, "expired-token") is None

    async def test_reading_an_expired_session_deletes_it(self, session: AsyncSession) -> None:
        """Otherwise a sweeper has to exist for the table not to grow forever."""
        user = await auth.account_for(session, "h@example.com")
        past = datetime.now(UTC) - timedelta(seconds=1)
        await IdentityRepository(session).create_session("dead-token", user.id, past)

        await auth.session_user(session, "dead-token")
        assert await IdentityRepository(session).session_by_id("dead-token") is None

    async def test_logging_out_kills_the_token(self, session: AsyncSession) -> None:
        user = await auth.account_for(session, "i@example.com")
        token = await auth.open_session(session, user.id)

        await auth.close_session(session, token)
        assert await auth.session_user(session, token) is None

    async def test_an_unknown_token_is_nobody(self, session: AsyncSession) -> None:
        assert await auth.session_user(session, "never-issued") is None


@needs_postgres
class TestSweepingSessions:
    async def test_only_expired_rows_go(self, session: AsyncSession) -> None:
        user = await auth.account_for(session, "sw@example.com")
        live = await auth.open_session(session, user.id)
        past = datetime.now(UTC) - timedelta(seconds=1)
        await IdentityRepository(session).create_session("stale", user.id, past)

        assert await auth.sweep_expired_sessions(session) == 1
        assert await auth.session_user(session, live) == user


@needs_postgres
class TestMembership:
    """A row is access, and the rows are what Jira said. No row, no access."""

    async def test_a_new_account_may_read_nothing(self, session: AsyncSession) -> None:
        """Otherwise a person nobody has recorded anything about is an administrator."""
        user = await auth.account_for(session, "mem@example.com")

        assert await permission.readable_projects(user) == frozenset()
        assert await permission.can_read_project(user, "MYC") is False

    async def test_jira_s_answer_becomes_the_access(self, session: AsyncSession) -> None:
        user = await auth.account_for(session, "mem2@example.com")

        await AccountRepository(session).replace_projects(user.id, ["MYC", "OPS"])

        assert await AccountRepository(session).projects_for(user.id) == frozenset({"MYC", "OPS"})

    async def test_a_project_lost_in_jira_is_lost_here(self, session: AsyncSession) -> None:
        """Replaced, never merged: a merge would only ever add."""
        user = await auth.account_for(session, "mem3@example.com")
        repo = AccountRepository(session)
        await repo.replace_projects(user.id, ["MYC", "OPS"])

        await repo.replace_projects(user.id, ["OPS"])

        assert await repo.projects_for(user.id) == frozenset({"OPS"})

    async def test_nothing_from_jira_means_nothing_here(self, session: AsyncSession) -> None:
        user = await auth.account_for(session, "mem4@example.com")
        repo = AccountRepository(session)
        await repo.replace_projects(user.id, ["MYC"])

        await repo.replace_projects(user.id, [])

        assert await repo.projects_for(user.id) == frozenset()

    async def test_one_person_s_access_is_not_another_s(self, session: AsyncSession) -> None:
        one = await auth.account_for(session, "mem6@example.com")
        two = await auth.account_for(session, "mem7@example.com")
        await AccountRepository(session).replace_projects(one.id, ["MYC"])

        assert await AccountRepository(session).projects_for(two.id) == frozenset()


@needs_postgres
class TestTheGoogleRoutesOverHttp:
    """Four routes, and what matters about them is where they send a browser."""

    @pytest.fixture(autouse=True)
    def _codes(self, redis: CodeRedis) -> None:
        """Signing in here goes through the emailed code."""

    @staticmethod
    def _sign_in(client: TestClient, email: str = "cal@example.com") -> None:
        TestOverHttp.sign_in(client, email)

    def test_an_unconfigured_deployment_says_so_rather_than_offering_a_button(
        self, client: TestClient
    ) -> None:
        """`configured` is about the machine, not the person."""
        self._sign_in(client)

        body = client.get("/auth/google").json()

        assert body["configured"] is False
        assert body["who"] is None

    def test_every_plugin_is_listed_and_an_unknown_one_is_404(self, client: TestClient) -> None:
        self._sign_in(client)

        keys = [p["key"] for p in client.get("/auth/plugins").json()]

        assert keys == ["google", "jira"]
        assert client.get("/auth/nope").status_code == 404
        assert client.get("/auth/methods").status_code == 200

    def test_starting_a_round_it_cannot_finish_is_refused(self, client: TestClient) -> None:
        self._sign_in(client)

        assert client.get("/auth/google/start", follow_redirects=False).status_code == 503

    def test_a_cancelled_consent_comes_back_to_the_app(self, client: TestClient) -> None:
        """Somebody pressed Cancel on Google's screen."""
        response = client.get(
            "/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False
        )

        assert response.status_code == 307
        assert "google_error=access_denied" in response.headers["location"]

    def test_a_callback_with_nothing_in_it_still_redirects(self, client: TestClient) -> None:
        response = client.get("/auth/google/callback", follow_redirects=False)

        assert response.status_code == 307
        assert "google_error=cancelled" in response.headers["location"]

    def test_a_signed_out_callback_connects_nothing(self, client: TestClient) -> None:
        """Only the account that started the round may finish it: still a redirect, not a 401."""
        response = client.get(
            "/auth/google/callback",
            params={"code": "c", "state": "never-issued"},
            follow_redirects=False,
        )

        assert response.status_code == 307
        assert "google_error=signed_out" in response.headers["location"]

    def test_a_callback_with_an_unknown_state_fails(self, client: TestClient) -> None:
        self._sign_in(client)
        response = client.get(
            "/auth/google/callback",
            params={"code": "c", "state": "never-issued"},
            follow_redirects=False,
        )

        assert response.status_code == 307
        assert "google_error=failed" in response.headers["location"]

    def test_disconnecting_what_was_never_connected_is_not_an_error(
        self, client: TestClient
    ) -> None:
        """The end state is what was asked for, which is the whole of what DELETE promises."""
        self._sign_in(client)

        assert client.delete("/auth/google").status_code == 204

    def test_signed_out_learns_nothing(self, client: TestClient) -> None:
        assert client.get("/auth/google").status_code == 401
        assert client.delete("/auth/google").status_code == 401


def test_one_callback_tells_a_sign_in_from_a_connection() -> None:
    """One redirect uri in the Google console: the state says which round came back."""
    from mycel.services import google_signin

    assert google_signin.is_signin("signin.abc")
    assert not google_signin.is_signin("abc")
    assert not google_signin.is_signin(None)
