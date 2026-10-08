"""What every OAuth provider here shares: the consent state, the callback, the token POST."""

import secrets
from typing import Any

import httpx2

from mycel.core.config import get_settings
from mycel.infra.redis.client import get_client

HTTP_TIMEOUT_S = 15.0

#: How long a consent round may take.
STATE_TTL_S = 600


async def start_state(provider: str, user_id: int) -> str:
    """A fresh state for one consent round, remembered as this person's."""
    state = secrets.token_urlsafe(32)
    client = await get_client()
    await client.set(_state_key(provider, state), str(user_id), ex=STATE_TTL_S)
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
    async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
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
