"""One person's standing permission to reach Jira as themselves, and what guards it.

The consent round is `services/google_oauth.py`'s, written in batch 051 and used a second
time here. So what is pinned is what is *different* about Jira, which is four things:

**The argument for per-person consent is authorship, not security.** Reading on a shared
token was fine; writing on one puts the host's name on every comment, and Jira cannot
correct the author of an event already written. Nothing in a test can assert that directly
— what it can assert is that there is no shared-token path left to fall back to.

**No person's grant carries the background sync.** It runs on the deployment's service
account; a person's grant only asks Jira what they may browse and writes as them.

**One scope is asked for conditionally.** A deployment that never creates a project must
never grant the right to, because a consent screen that over-asks describes an app that
does not exist.

No network and no Redis: the token endpoint is a `MockTransport` and the state store is a
dict. Postgres is the other half of this module and is covered in `test_postgres.py`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from cryptography.fernet import Fernet

from mycel.core.config import get_settings
from mycel.core.exceptions import ConfigError
from mycel.services import jira_oauth as oauth
from mycel.services.jira_oauth import JiraAuthError, NotConnected
from mycel.services.tokens import TokenUnreadable, seal, unseal

pytestmark = pytest.mark.anyio

_REAL_CLIENT = httpx2.AsyncClient
KEY = Fernet.generate_key().decode()


class FakeRedis:
    """Enough of the client for the state round: set with a TTL, and read-and-delete."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)


def _routes(answers: dict[str, Any], status: int = 200) -> Any:
    """Atlassian, answering by path fragment.

    Several routes rather than one payload because an exchange is three calls — the token,
    then the site, then who consented — and the interesting failures are in the last two.

    Longest fragment first, because Atlassian nests one of these inside another:
    `/oauth/token/accessible-resources` contains `/oauth/token`, so first-match order
    would answer the site lookup with the token payload.
    """

    def handler(request: httpx2.Request) -> httpx2.Response:
        for fragment in sorted(answers, key=len, reverse=True):
            if fragment in str(request.url):
                return httpx2.Response(status, json=answers[fragment])
        return httpx2.Response(404, json={})

    def _client(**kwargs: Any) -> httpx2.AsyncClient:
        kwargs.pop("transport", None)
        return _REAL_CLIENT(transport=httpx2.MockTransport(handler), **kwargs)

    return _client


#: A whole consent round that works, for the tests that are about something else.
WHOLE_ROUND = {
    "/oauth/token": {"refresh_token": "rt-1", "access_token": "at-1", "scope": "read:jira-work"},
    "accessible-resources": [{"id": "cloud-1", "name": "acme"}],
    "/myself": {"accountId": "acct-7", "displayName": "Nam Nguyen"},
}


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_CLIENT_ID", "jira-client-id")
    monkeypatch.setenv("JIRA_CLIENT_SECRET", "jira-client-secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", KEY)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://mycel.example.com")
    monkeypatch.delenv("JIRA_ALLOW_CREATE_PROJECT", raising=False)
    get_settings.cache_clear()


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()

    async def _get_client() -> FakeRedis:
        return fake

    monkeypatch.setattr(oauth, "get_client", _get_client)
    return fake


class TestWhetherThisDeploymentCanConnectAnything:
    def test_nothing_set_is_not_configured(self) -> None:
        """The default deployment. It runs, it just reads no board."""
        assert oauth.configured() is False

    def test_a_client_without_a_key_is_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Connecting anyway would store a refresh token readably, which is worse than
        refusing — and this is the state a half-finished setup actually reaches."""
        monkeypatch.setenv("JIRA_CLIENT_ID", "jira-client-id")
        monkeypatch.setenv("JIRA_CLIENT_SECRET", "jira-client-secret")
        monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
        get_settings.cache_clear()

        assert oauth.configured() is False

    def test_all_three_is_configured(self, configured: None) -> None:
        assert oauth.configured() is True

    async def test_an_unconfigured_deployment_refuses_rather_than_guesses(self) -> None:
        with pytest.raises(ConfigError):
            await oauth.consent_url(7)


class TestWhatTheConsentScreenAsksFor:
    async def test_the_four_everyday_scopes_are_always_asked_for(
        self, configured: None, redis: FakeRedis
    ) -> None:
        """`offline_access` is the one without which there is no background sync at all —
        no refresh token means a grant that stops working within the hour."""
        query = parse_qs(urlsplit(await oauth.consent_url(7)).query)

        assert query["scope"][0].split() == [
            "read:jira-work",
            "read:jira-user",
            "write:jira-work",
            "offline_access",
        ]

    async def test_the_admin_scope_is_absent_until_the_deployment_arms_it(
        self, configured: None, redis: FakeRedis
    ) -> None:
        """A deployment that never creates a project must never be granted the right to."""
        query = parse_qs(urlsplit(await oauth.consent_url(7)).query)

        assert oauth.PROJECT_SCOPE not in query["scope"][0]

    async def test_the_admin_scope_appears_once_it_is_armed(
        self, configured: None, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JIRA_ALLOW_CREATE_PROJECT", "true")
        get_settings.cache_clear()

        query = parse_qs(urlsplit(await oauth.consent_url(7)).query)

        assert oauth.PROJECT_SCOPE in query["scope"][0]

    async def test_it_forces_the_consent_prompt(self, configured: None, redis: FakeRedis) -> None:
        """Without it a reconnect comes back with an access token and nothing to store,
        and the account is connected in a way that stops working within the hour."""
        query = parse_qs(urlsplit(await oauth.consent_url(7)).query)

        assert query["prompt"] == ["consent"]

    async def test_the_redirect_matches_the_registered_callback(
        self, configured: None, redis: FakeRedis
    ) -> None:
        """It has to match the app's callback URL exactly or Atlassian refuses the round."""
        query = parse_qs(urlsplit(await oauth.consent_url(7)).query)

        assert query["redirect_uri"] == ["https://mycel.example.com/auth/jira/callback"]


class TestTheStateIsSpentOnce:
    async def test_the_state_says_whose_round_it_was(
        self, configured: None, redis: FakeRedis
    ) -> None:
        query = parse_qs(urlsplit(await oauth.consent_url(7)).query)

        assert await oauth.spend_state(query["state"][0]) == 7

    async def test_a_replayed_callback_connects_nothing(
        self, configured: None, redis: FakeRedis
    ) -> None:
        """A callback url lands in a history file and a referrer header, and neither may
        be enough to attach a second account."""
        state = parse_qs(urlsplit(await oauth.consent_url(7)).query)["state"][0]
        await oauth.spend_state(state)

        with pytest.raises(JiraAuthError):
            await oauth.spend_state(state)

    async def test_the_state_expires_on_its_own(self, configured: None, redis: FakeRedis) -> None:
        await oauth.consent_url(7)

        assert list(redis.ttls.values()) == [oauth.STATE_TTL_S]


class TestExchangingTheCode:
    async def test_a_grant_carries_the_site_and_who_consented(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Neither is in the token response, and both are needed before a write can carry
        a name: the cloud id addresses every later call, the account id is the author."""
        monkeypatch.setattr(httpx2, "AsyncClient", _routes(WHOLE_ROUND))

        grant = await oauth.exchange("code-from-atlassian")

        assert grant.cloud_id == "cloud-1"
        assert grant.account_id == "acct-7"
        assert grant.display_name == "Nam Nguyen"
        assert grant.refresh_token == "rt-1"
        # As granted, not as asked for: a site may hand back less.
        assert grant.scope == "read:jira-work"

    async def test_a_response_with_no_refresh_token_names_the_way_out(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure worth naming: everything else about that response looks fine, and
        the account would be connected in a way that stops syncing within the hour."""
        monkeypatch.setattr(
            httpx2, "AsyncClient", _routes({**WHOLE_ROUND, "/oauth/token": {"access_token": "at"}})
        )

        with pytest.raises(JiraAuthError, match="offline_access"):
            await oauth.exchange("code")

    async def test_an_account_that_can_reach_no_site_is_refused_clearly(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Connecting with the wrong Atlassian account is a thing people do, and the row
        it would leave behind looks connected while reaching nothing."""
        monkeypatch.setattr(
            httpx2, "AsyncClient", _routes({**WHOLE_ROUND, "accessible-resources": []})
        )

        with pytest.raises(JiraAuthError, match="no Jira site"):
            await oauth.exchange("code")


class TestRefreshing:
    async def test_a_lapsed_grant_reads_as_not_connected(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Revoking the app is a thing people do and it is not a fault — it has to reach
        them as "connect it again" rather than as a traceback."""
        monkeypatch.setattr(
            httpx2, "AsyncClient", _routes({"/oauth/token": {"error": "invalid_grant"}}, status=400)
        )

        with pytest.raises(NotConnected):
            await oauth.access_token(seal("rt-1"))

    async def test_any_other_refusal_is_not_a_reconnect(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A broken client is not a lapsed grant, and telling somebody to reconnect sends
        them round a loop that cannot help."""
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            _routes({"/oauth/token": {"error": "invalid_client"}}, status=401),
        )

        with pytest.raises(JiraAuthError) as caught:
            await oauth.access_token(seal("rt-1"))

        assert not isinstance(caught.value, NotConnected)

    async def test_an_access_token_comes_back(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        routes = _routes({"/oauth/token": {"access_token": "at"}})
        monkeypatch.setattr(httpx2, "AsyncClient", routes)

        assert await oauth.access_token(seal("rt-1")) == "at"


class TestARotatedTokenIsKept:
    """New Atlassian apps rotate refresh tokens: a refresh that drops the successor works
    once, and the sync stops silently a few hours later."""

    async def test_the_successor_is_written_back(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kept: list[tuple[int, str]] = []

        class Repo:
            def __init__(self, _session: object) -> None: ...

            async def jira_account_locked(self, user_id: int) -> object:
                return type("Row", (), {"refresh_token_encrypted": seal("rt-1")})()

            async def set_jira_refresh_token(self, user_id: int, sealed: str) -> None:
                kept.append((user_id, sealed))

        @asynccontextmanager
        async def _scope() -> AsyncIterator[None]:
            yield None

        monkeypatch.setattr(oauth, "AppRepository", Repo)
        monkeypatch.setattr(oauth, "session_scope", _scope)
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            _routes({"/oauth/token": {"access_token": "at", "refresh_token": "rt-2"}}),
        )

        assert await oauth._access_for(7) == "at"
        assert [(uid, unseal(sealed)) for uid, sealed in kept] == [(7, "rt-2")]

    async def test_no_successor_leaves_the_row_alone(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kept: list[str] = []

        class Repo:
            def __init__(self, _session: object) -> None: ...

            async def jira_account_locked(self, user_id: int) -> object:
                return type("Row", (), {"refresh_token_encrypted": seal("rt-1")})()

            async def set_jira_refresh_token(self, user_id: int, sealed: str) -> None:
                kept.append(sealed)

        @asynccontextmanager
        async def _scope() -> AsyncIterator[None]:
            yield None

        monkeypatch.setattr(oauth, "AppRepository", Repo)
        monkeypatch.setattr(oauth, "session_scope", _scope)
        monkeypatch.setattr(
            httpx2, "AsyncClient", _routes({"/oauth/token": {"access_token": "at"}})
        )

        assert await oauth._access_for(7) == "at"
        assert kept == []


class TestTheTokenAtRest:
    def test_what_reaches_postgres_is_not_the_token(self, configured: None) -> None:
        """A database dump must not be a list of Jira accounts."""
        sealed = seal("rt-1")

        assert "rt-1" not in sealed
        assert unseal(sealed) == "rt-1"

    def test_one_key_covers_both_providers(self, configured: None) -> None:
        """`TOKEN_ENCRYPTION_KEY`, not `GOOGLE_TOKEN_KEY`. The old name said Google about
        an Atlassian token, which sends the next reader to the wrong file."""
        from mycel.services import google_oauth

        assert google_oauth.unseal(seal("rt-1")) == "rt-1"

    def test_a_token_sealed_under_another_key_is_unreadable(self, configured: None) -> None:
        """A rotated key looks exactly like a lapsed grant from the person's side."""
        stale = Fernet(Fernet.generate_key()).encrypt(b"rt-1").decode()

        with pytest.raises(TokenUnreadable):
            unseal(stale)

    async def test_an_unreadable_token_reaches_the_person_as_reconnect(
        self, configured: None
    ) -> None:
        """Raising `TokenUnreadable` out of a refresh would be a traceback for something
        the person fixes with one click."""
        stale = Fernet(Fernet.generate_key()).encrypt(b"rt-1").decode()

        with pytest.raises(NotConnected, match="connect your account again"):
            await oauth.access_token(stale)
