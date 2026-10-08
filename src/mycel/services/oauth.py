"""What every OAuth provider here shares: consent state, token POST, sealed tokens."""

import secrets
from typing import Any
from urllib.parse import urlencode

import httpx2
from pydantic import SecretStr

from mycel.core.config import get_settings
from mycel.core.exceptions import ConfigError, MycelError
from mycel.infra.redis.client import get_client
from mycel.services.tokens import TokenUnreadable, unseal

HTTP_TIMEOUT_SECONDS = 15.0

#: How long a consent round may take.
STATE_TTL_SECONDS = 600


async def consent_url(provider: str, auth_url: str, user_id: int, params: dict[str, str]) -> str:
    """The provider's consent screen, carrying a fresh state remembered as this person's."""
    state = await start_state(provider, user_id)
    return f"{auth_url}?{urlencode({**params, 'state': state})}"


async def owner_of(provider: str, state: str, error: type[MycelError]) -> int:
    """Whose consent round a callback belongs to, or `error`."""
    user_id = await spend_state(provider, state)
    if user_id is None:
        raise error("that consent link has expired; start again from settings")
    return user_id


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


async def start_state(provider: str, user_id: int) -> str:
    """A fresh state for one consent round, remembered as this person's."""
    state = secrets.token_urlsafe(32)
    client = await get_client()
    await client.set(_state_key(provider, state), str(user_id), ex=STATE_TTL_SECONDS)
    return state


async def spend_state(provider: str, state: str) -> int | None:
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
    async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(url, data=data, json=json)
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
