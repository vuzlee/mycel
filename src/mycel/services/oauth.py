"""What every OAuth provider here shares: consent state, token POST, sealed tokens."""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx2
from pydantic import SecretStr

from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError, MycelError
from mycel.infra.http import shared
from mycel.infra.redis.client import get_client
from mycel.services.tokens import TokenUnreadable, key_set, unseal

HTTP_TIMEOUT_SECONDS = 15.0

#: How long a consent round may take.
STATE_TTL_SECONDS = 600


@dataclass(frozen=True)
class OAuthProvider:
    """One provider's constants; the flow every provider shares is its methods."""

    key: str
    name: str
    env: str
    auth_url: str
    token_url: str
    callback_path: str
    #: The client id and secret fields on `Settings`.
    client: Callable[[Settings], tuple[str | None, SecretStr | None]]
    #: Atlassian takes JSON at its token endpoint; Google takes a form.
    json_body: bool
    error: type[MycelError]
    revoked: type[MycelError]
    revoked_codes: tuple[str, ...]
    #: What to tell someone whose consent came back without a refresh token.
    no_refresh_hint: str

    def configured(self, settings: Settings | None = None) -> bool:
        cfg = settings or get_settings()
        client_id, secret = self.client(cfg)
        return bool(client_id and secret and key_set(cfg))

    def credentials(self) -> tuple[str, str]:
        client_id, secret = self.client(get_settings())
        return credentials(client_id, secret, self.configured(), self.env)

    def redirect_uri(self) -> str:
        return redirect_uri(self.callback_path)

    async def consent_url(self, user_id: int, params: dict[str, str]) -> str:
        client_id, _ = self.credentials()
        base = {"client_id": client_id, "redirect_uri": self.redirect_uri()}
        return await consent_url(self.key, self.auth_url, user_id, {**base, **params})

    async def owner_of(self, state: str, user_id: int) -> int:
        return await owner_of(self.key, state, user_id, self.error)

    async def code_grant(self, code: str) -> dict[str, Any]:
        """Exchange a consent code; the response must carry a refresh token."""
        payload = await self._token_call(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri(),
            }
        )
        if not payload.get("refresh_token"):
            raise self.error(f"{self.name} returned no refresh token. {self.no_refresh_hint}")
        return payload

    async def refresh_grant(self, sealed: str) -> dict[str, Any]:
        """A refresh-token round; the response must carry an access token."""
        payload = await self._token_call(
            {"grant_type": "refresh_token", "refresh_token": self.unseal(sealed)}
        )
        if not payload.get("access_token"):
            raise self.error(f"{self.name} returned no access token")
        return payload

    def unseal(self, sealed: str) -> str:
        return unseal_for(sealed, self.name, self.revoked)

    async def _token_call(self, data: dict[str, str]) -> dict[str, Any]:
        client_id, client_secret = self.credentials()
        return await token_call(
            self.token_url,
            {**data, "client_id": client_id, "client_secret": client_secret},
            as_json=self.json_body,
            name=self.name,
            error=self.error,
            revoked=self.revoked,
            revoked_codes=self.revoked_codes,
        )


async def consent_url(provider: str, auth_url: str, user_id: int, params: dict[str, str]) -> str:
    """The provider's consent screen, carrying a fresh state remembered as this person's."""
    state = await _start_state(provider, user_id)
    return f"{auth_url}?{urlencode({**params, 'state': state})}"


async def owner_of(provider: str, state: str, user_id: int, error: type[MycelError]) -> int:
    """`user_id` if the round is theirs, else `error`: a link someone else started is refused."""
    owner = await _spend_state(provider, state)
    if owner is None:
        raise error("that consent link has expired; start again from settings")
    if owner != user_id:
        raise error("that consent link was started by another account")
    return owner


async def token_call(
    url: str,
    data: dict[str, str],
    *,
    as_json: bool,
    name: str,
    error: type[MycelError],
    revoked: type[MycelError],
    revoked_codes: tuple[str, ...],
) -> dict[str, Any]:
    """One POST to a token endpoint; a revoked grant raises `revoked`, others `error`."""
    try:
        status, payload = (
            await post_token(url, json=data) if as_json else await post_token(url, data=data)
        )
    except httpx2.HTTPError as exc:
        raise error(f"{name} could not be reached: {exc}") from exc
    if status >= 400:
        code = str(payload.get("error", status))
        if code in revoked_codes:
            raise revoked(f"your {name} account is no longer connected; connect it again")
        raise error(f"{name} refused the request: {code}")
    return payload


def unseal_for(sealed: str, name: str, revoked: type[MycelError]) -> str:
    """Decrypt a stored refresh token; a rotated key means connecting again."""
    try:
        return unseal(sealed)
    except TokenUnreadable as exc:
        msg = f"the stored {name} token cannot be read; connect your account again"
        raise revoked(msg) from exc


def credentials(
    client_id: str | None, secret: SecretStr | None, configured: bool, env: str
) -> tuple[str, str]:
    """The client id and secret, or `ConfigError` naming what to set."""
    if not configured or client_id is None or secret is None:
        raise ConfigError(
            f"this deployment has no {env} OAuth client configured; "
            f"set {env}_CLIENT_ID, {env}_CLIENT_SECRET and TOKEN_ENCRYPTION_KEY"
        )
    return client_id, secret.get_secret_value()


async def _start_state(provider: str, user_id: int) -> str:
    """A fresh state for one consent round, remembered as this person's."""
    state = secrets.token_urlsafe(32)
    client = await get_client()
    await client.set(_state_key(provider, state), str(user_id), ex=STATE_TTL_SECONDS)
    return state


async def _spend_state(provider: str, state: str) -> int | None:
    """Whose round this callback belongs to, or `None`."""
    client = await get_client()
    user_id = await client.getdel(_state_key(provider, state))
    return None if user_id is None else int(user_id)


def redirect_uri(callback_path: str) -> str:
    """Where the provider sends the person back. Must match the registered uri exactly."""
    return f"{get_settings().public_base_url.rstrip('/')}{callback_path}"


async def post_token(
    url: str, *, data: dict[str, str] | None = None, json: Any = None
) -> tuple[int, dict[str, Any]]:
    """One POST to a token endpoint: the status and the JSON body, or `{}` when it has none."""
    response = await shared().post(url, data=data, json=json, timeout=HTTP_TIMEOUT_SECONDS)
    payload: dict[str, Any] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            payload = parsed
    except ValueError:
        pass
    return response.status_code, payload


def _state_key(provider: str, state: str) -> str:
    return f"mycel:{provider}:state:{state}"
