"""One person's standing permission to reach their own calendar, and what guards it.

Four things here are load-bearing, and each of them is one line of code that a refactor
could quietly drop:

**A refresh token never rests in the clear.** It opens one calendar until its owner revokes
it, so the only thing Postgres ever holds is a Fernet ciphertext. A test that the encryption
happens is a test that a database dump is not a list of calendars.

**A half-configured deployment counts as unconfigured.** A client with no encryption key
would connect an account and store the token readably, which is worse than refusing. The
key is `TOKEN_ENCRYPTION_KEY` since batch 060, shared with Jira — one key, two providers.

**`state` is spent once.** The callback arrives as a redirect, so the value nobody saw is the
only thing tying it to the person who started it, and a url in a history file must not be
replayable.

**`invalid_grant` is not a fault.** It is what Google says when someone revoked access, and
it has to reach the person as "connect it again" rather than as a traceback.

No network and no Redis: the token endpoint is a `MockTransport` and the state store is a
dict. Postgres is `services/google_oauth.py`'s other half and is not touched here.
"""

from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from cryptography.fernet import Fernet

from mycel.core.config import get_settings
from mycel.core.exceptions import ConfigError
from mycel.services import google_oauth as oauth
from mycel.services.google_oauth import GoogleError, NotConnected
from tests.fakes import FakeRedis

pytestmark = pytest.mark.anyio

_REAL_CLIENT = httpx2.AsyncClient
KEY = Fernet.generate_key().decode()


def _answers(payload: dict[str, Any], status: int = 200) -> Any:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=payload)

    def _client(**kwargs: Any) -> httpx2.AsyncClient:
        kwargs.pop("transport", None)
        return _REAL_CLIENT(transport=httpx2.MockTransport(handler), **kwargs)

    return _client


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", KEY)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://mycel.example.com")
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
        """The default deployment. It runs, it just has no calendar in it."""
        assert oauth.configured() is False

    def test_a_client_without_a_key_is_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Half-configured is the state a deployment actually reaches, and connecting anyway
        would store a refresh token readably — worse than refusing."""
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
        get_settings.cache_clear()

        assert oauth.configured() is False

    def test_all_three_is_configured(self, configured: None) -> None:
        assert oauth.configured() is True

    async def test_an_unconfigured_deployment_refuses_rather_than_guesses(self) -> None:
        with pytest.raises(ConfigError):
            await oauth.consent_url(7)


class TestTheConsentUrl:
    async def test_it_asks_for_a_refresh_token(self, configured: None, redis: FakeRedis) -> None:
        """`access_type=offline` with `prompt=consent` is the whole of whether a token comes
        back: Google sends one on the first consent only, so every round forces the prompt
        and a reconnect is always a working reconnect."""
        query = parse_qs(urlsplit(await oauth.consent_url(7)).query)

        assert query["access_type"] == ["offline"]
        assert query["prompt"] == ["consent"]

    async def test_it_asks_for_the_narrowest_scopes(
        self, configured: None, redis: FakeRedis
    ) -> None:
        """`calendar.events` cannot delete a calendar and `gmail.readonly` cannot send or
        delete; `calendar` and `gmail.modify` would each be a great deal wider."""
        query = parse_qs(urlsplit(await oauth.consent_url(7)).query)

        assert query["scope"] == [
            "openid email https://www.googleapis.com/auth/calendar.events "
            "https://www.googleapis.com/auth/gmail.readonly"
        ]

    async def test_the_redirect_matches_the_registered_callback(
        self, configured: None, redis: FakeRedis
    ) -> None:
        """It has to match the client's registered uri exactly or Google refuses the round."""
        query = parse_qs(urlsplit(await oauth.consent_url(7)).query)

        assert query["redirect_uri"] == ["https://mycel.example.com/auth/google/callback"]


class TestTheStateIsSpentOnce:
    async def test_the_state_says_whose_round_it_was(
        self, configured: None, redis: FakeRedis
    ) -> None:
        query = parse_qs(urlsplit(await oauth.consent_url(7)).query)

        assert await oauth.spend_state(query["state"][0]) == 7

    async def test_a_replayed_callback_connects_nothing(
        self, configured: None, redis: FakeRedis
    ) -> None:
        """A callback url lands in a history file and a referrer header, and neither of them
        may be enough to attach a second account."""
        state = parse_qs(urlsplit(await oauth.consent_url(7)).query)["state"][0]
        await oauth.spend_state(state)

        with pytest.raises(GoogleError):
            await oauth.spend_state(state)

    async def test_an_invented_state_is_refused(self, configured: None, redis: FakeRedis) -> None:
        with pytest.raises(GoogleError):
            await oauth.spend_state("not-a-round")

    async def test_the_state_expires_on_its_own(self, configured: None, redis: FakeRedis) -> None:
        """An abandoned consent round must disappear without anybody tidying up."""
        await oauth.consent_url(7)

        assert list(redis.ttls.values()) == [oauth.STATE_TTL_S]


class TestExchangingTheCode:
    async def test_a_grant_carries_the_email_and_the_scopes_granted(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The scope is as granted, not as asked for: Google may hand back less, and a tool
        that assumes otherwise fails at the write rather than at the connect."""
        id_token = "header." + _b64({"email": "dev@example.com"}) + ".signature"
        monkeypatch.setattr(
            httpx2,
            "AsyncClient",
            _answers({"refresh_token": "1//refresh", "id_token": id_token, "scope": "openid"}),
        )

        grant = await oauth.exchange("code-from-google")

        assert grant.email == "dev@example.com"
        assert grant.refresh_token == "1//refresh"
        assert grant.scope == "openid"

    async def test_a_response_with_no_refresh_token_names_the_way_out(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure worth naming: everything else about that response looks fine, and the
        account would be connected in a way that stops working within the hour."""
        monkeypatch.setattr(httpx2, "AsyncClient", _answers({"access_token": "ya29."}))

        with pytest.raises(GoogleError) as caught:
            await oauth.exchange("code-from-google")

        assert "myaccount.google.com/permissions" in str(caught.value)

    async def test_an_unreadable_id_token_still_connects(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The address is a label for a screen. Losing it must not cost the connection."""
        monkeypatch.setattr(httpx2, "AsyncClient", _answers({"refresh_token": "1//refresh"}))

        assert (await oauth.exchange("code")).email == "(unknown)"


class TestRefreshing:
    async def test_a_revoked_grant_reads_as_not_connected(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Revoking access is a thing people do, and it is not a fault — it has to reach them
        as "connect it again" rather than as a traceback."""
        monkeypatch.setattr(httpx2, "AsyncClient", _answers({"error": "invalid_grant"}, status=400))

        with pytest.raises(NotConnected):
            await oauth.access_token(oauth.seal("1//refresh"))

    async def test_any_other_refusal_is_a_google_error(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A broken client is not a revoked grant, and telling somebody to reconnect would
        send them round a loop that cannot help."""
        monkeypatch.setattr(
            httpx2, "AsyncClient", _answers({"error": "invalid_client"}, status=401)
        )

        with pytest.raises(GoogleError) as caught:
            await oauth.access_token(oauth.seal("1//refresh"))

        assert not isinstance(caught.value, NotConnected)

    async def test_an_access_token_comes_back(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(httpx2, "AsyncClient", _answers({"access_token": "ya29.token"}))

        assert await oauth.access_token(oauth.seal("1//refresh")) == "ya29.token"


class TestTheTokenAtRest:
    def test_what_reaches_postgres_is_not_the_token(self, configured: None) -> None:
        """A database dump must not be a list of calendars."""
        sealed = oauth.seal("1//refresh")

        assert "1//refresh" not in sealed
        assert oauth.unseal(sealed) == "1//refresh"

    def test_a_token_sealed_under_another_key_reads_as_not_connected(
        self, configured: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rotated key looks exactly like a revoked grant from the person's side, and the
        answer to both is the same sentence."""
        stale = Fernet(Fernet.generate_key()).encrypt(b"1//refresh").decode()

        with pytest.raises(NotConnected):
            oauth.unseal(stale)

    def test_a_key_that_is_not_a_key_is_a_config_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Wrong at start-up, not at the first person who tries to connect."""
        monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "not-base32-and-not-32-bytes")
        get_settings.cache_clear()

        with pytest.raises(ConfigError):
            oauth.seal("1//refresh")


def _b64(claims: dict[str, str]) -> str:
    """The middle segment of an id token: base64url of the claims, padding stripped."""
    import base64
    import json

    return base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
