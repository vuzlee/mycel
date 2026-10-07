"""What every OAuth provider here shares: the consent state, the callback, the token POST.

Each provider keeps its own errors and wording; this holds only the steps that are the
same for Google and Atlassian.
"""

import secrets
from typing import Any

import httpx2

from mycel.core.config import get_settings
from mycel.infra.redis.client import get_client

HTTP_TIMEOUT_S = 15.0

#: How long a consent round may take. Long enough to read a consent screen and sign in.
STATE_TTL_S = 600


async def start_state(provider: str, user_id: int) -> str:
    """A fresh state for one consent round, remembered as this person's."""
    state = secrets.token_urlsafe(32)
    client = await get_client()
    await client.set(_state_key(provider, state), str(user_id), ex=STATE_TTL_S)
    return state


async def spend_state(provider: str, state: str) -> int | None:
    """Whose round this callback belongs to, or `None`.

    Spent on first use: a callback url that lands in a history file or a referrer header
    cannot be replayed into a second connection.
    """
    client = await get_client()
    user_id = await client.getdel(_state_key(provider, state))
    return None if user_id is None else int(user_id)


def redirect_uri(callback_path: str) -> str:
    """Where the provider sends the person back. Must match the registered uri exactly."""
    return f"{get_settings().public_base_url.rstrip('/')}{callback_path}"


async def post_token(
    url: str, *, data: dict[str, str] | None = None, json: Any = None
) -> tuple[int, dict[str, Any]]:
    """One POST to a token endpoint: the status and the JSON body, or `{}` when it has none.

    The body is kept even on an error: it is the only place a provider says *why*, and a
    refused grant there is the difference between "connect again" and "something is broken".
    Raises `httpx2.HTTPError` when the provider cannot be reached; the caller words it.
    """
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
