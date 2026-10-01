"""One person's standing permission to reach their own Google calendar.

**Per-user consent, not a service account.** A service account writes to a calendar the
deployment owns, which is the wrong calendar for "what have I got this afternoon" — the
only calendar worth reading is the one the person asking already lives in. So there is a
consent round, and what it leaves behind is a refresh token.

**The refresh token is a password with a long life.** It opens one calendar until its owner
revokes it, so it is encrypted before it reaches Postgres and decrypted only here, on the
way to a request. It never appears in a log line, a Langfuse span, or a prompt — the
functions below return access tokens and events, and nothing returns the refresh token.

**Three scopes, and `email` is the odd one.** `calendar.events` reads and creates events
and cannot delete a calendar; `openid email` is identity only, and it is here because the
settings screen has to be able to say *which* Google account is connected. Asking for
`calendar` instead would be one word shorter and a great deal wider.

**`state` lives in Redis, not in a cookie.** The callback arrives as a redirect from
Google, so the only thing tying it to the person who started it is a value they never saw;
one Redis key with a ten-minute TTL is that value, and it is spent on first use so a
replayed callback connects nothing.
"""

import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx2
from cryptography.fernet import Fernet, InvalidToken

from mycel.core.config import get_settings
from mycel.core.exceptions import ConfigError, MycelError
from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.app import AppRepository, GoogleAccountRow
from mycel.infra.postgres.session import session_scope
from mycel.infra.redis.client import get_client

log = get_logger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

#: Narrowest that does the job. `calendar.events` cannot delete a calendar; `email` is
#: identity, so the settings screen can name the account that is connected.
SCOPES = ("openid", "email", "https://www.googleapis.com/auth/calendar.events")

CALLBACK_PATH = "/auth/google/callback"
HTTP_TIMEOUT_S = 15.0

#: Long enough to read a consent screen, short enough that an abandoned one is gone.
STATE_TTL_S = 600


class GoogleError(MycelError):
    """The consent round, or a token exchange, did not work."""


class NotConnected(GoogleError):
    """This person has no usable Google account attached.

    Either they never connected one, or they revoked it and the refresh token no longer
    works. Both are answered the same way — connect it again in settings — and neither is
    a bug, which is why callers turn this into a sentence rather than letting it raise.
    """


@dataclass(frozen=True)
class Grant:
    """What came back from a consent round, ready for the repository."""

    email: str
    refresh_token: str
    scope: str


def configured() -> bool:
    """Whether this deployment can connect an account at all.

    All three: the client is who is asking, and the key is what keeps the answer secret. A
    deployment with a client and no key would store a refresh token in the clear, so it
    counts as not configured rather than as configured badly.
    """
    cfg = get_settings()
    return bool(cfg.google_client_id and cfg.google_client_secret and cfg.google_token_key)


async def consent_url(user_id: int) -> str:
    """Where to send someone so Google can ask them.

    `access_type=offline` with `prompt=consent` is what returns a refresh token. Google
    sends one on the *first* consent only, and a second round without `prompt=consent`
    comes back with an access token and nothing to store — so the prompt is forced, and a
    reconnect is always a working reconnect.
    """
    client_id, _ = _client()
    state = secrets.token_urlsafe(32)
    client = await get_client()
    await client.set(_state_key(state), str(user_id), ex=STATE_TTL_S)

    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


async def spend_state(state: str) -> int:
    """Whose consent round this callback belongs to. Raises `GoogleError` if it is not one.

    Spent on first use: a callback url that lands in a history file or a referrer header
    cannot be replayed into a second connection.
    """
    client = await get_client()
    user_id = await client.getdel(_state_key(state))
    if user_id is None:
        raise GoogleError("that consent link has expired; start again from settings")
    return int(user_id)


async def exchange(code: str) -> Grant:
    """Turn the code Google redirected with into something worth keeping.

    Raises `GoogleError` when Google refuses, and when it answers without a refresh token —
    which is the failure worth naming, because everything else about that response looks
    fine and the account would be connected in a way that stops working within the hour.
    """
    client_id, client_secret = _client()
    payload = await _token_call(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": _redirect_uri(),
            "grant_type": "authorization_code",
        }
    )

    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise GoogleError(
            "Google returned no refresh token. Remove Mycel at "
            "myaccount.google.com/permissions and connect again."
        )
    return Grant(
        email=_email_from(payload),
        refresh_token=str(refresh_token),
        # As granted, not as asked for. Google may hand back less, and a tool that assumes
        # otherwise fails at the write rather than at the connect.
        scope=str(payload.get("scope", "")),
    )


async def access_token(refresh_token_encrypted: str) -> str:
    """A fresh access token for one person, from the token kept for them.

    Raises `NotConnected` when Google says `invalid_grant` — the one error that is not a
    fault: it means the person revoked access, and the answer is to connect again rather
    than to retry.
    """
    client_id, client_secret = _client()
    payload = await _token_call(
        {
            "refresh_token": unseal(refresh_token_encrypted),
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        }
    )
    token = payload.get("access_token")
    if not token:
        raise GoogleError("Google returned no access token")
    return str(token)


async def revoke(refresh_token_encrypted: str) -> None:
    """Tell Google to forget the grant. Failure is logged, never raised.

    The row is deleted either way: a person who asked to disconnect must end up
    disconnected here, whether or not Google was reachable when they asked.
    """
    try:
        async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            await client.post(REVOKE_URL, data={"token": unseal(refresh_token_encrypted)})
    except (httpx2.HTTPError, GoogleError) as exc:
        log.warning("google revoke failed", extra={"error": str(exc)})


async def connect(state: str, code: str) -> GoogleAccountRow:
    """Finish a consent round: check the state, exchange the code, keep the token.

    The exchange and the write are one call because of the trap they sit on — Google returns
    a refresh token on the first consent and never again, so a token received and not stored
    is an account that has to be revoked by hand before it can be connected again.
    """
    user_id = await spend_state(state)
    grant = await exchange(code)
    async with session_scope() as session:
        repo = AppRepository(session)
        await repo.upsert_google_account(
            user_id, grant.email, seal(grant.refresh_token), grant.scope
        )
        row = await repo.google_account(user_id)
    assert row is not None
    log.info("google account connected", extra={"user_id": user_id})
    return row


async def connected(user_id: int) -> GoogleAccountRow | None:
    """What this person has attached, for the settings screen. `None` is normal."""
    async with session_scope() as session:
        return await AppRepository(session).google_account(user_id)


async def disconnect(user_id: int) -> bool:
    """Forget the grant here, and ask Google to forget it too.

    Google is told first and its failure is only logged: the row goes either way, because a
    person who asked to disconnect must end up disconnected whether or not Google answered.
    """
    async with session_scope() as session:
        repo = AppRepository(session)
        row = await repo.google_account(user_id)
        if row is None:
            return False
        await revoke(row.refresh_token_encrypted)
        return await repo.delete_google_account(user_id)


async def token_for(user_id: int) -> str:
    """An access token for one person, or `NotConnected` with the sentence to show them.

    The one function the calendar calls. Fetched per use rather than cached: an access token
    lives under an hour, and a cache of them would be a second place a credential sits.
    """
    row = await connected(user_id)
    if row is None:
        raise NotConnected("no Google account is connected; connect one in settings")
    return await access_token(row.refresh_token_encrypted)


def seal(refresh_token: str) -> str:
    """Encrypt a refresh token for storage. The only thing that writes that column."""
    return _fernet().encrypt(refresh_token.encode()).decode()


def unseal(refresh_token_encrypted: str) -> str:
    """Decrypt a stored refresh token.

    A key that has been rotated makes every stored token unreadable, which is the same
    situation as a revoked grant from the person's point of view — so it is reported the
    same way, and reconnecting fixes it.
    """
    try:
        return _fernet().decrypt(refresh_token_encrypted.encode()).decode()
    except InvalidToken as exc:
        raise NotConnected(
            "the stored Google token cannot be read; connect your account again"
        ) from exc


async def _token_call(data: dict[str, str]) -> dict[str, object]:
    """One POST to the token endpoint, with Google's own error text kept.

    The body is the only place Google says *why*, and `invalid_grant` there is the
    difference between "connect again" and "something is broken".
    """
    try:
        async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            response = await client.post(TOKEN_URL, data=data)
    except httpx2.HTTPError as exc:
        raise GoogleError(f"Google could not be reached: {exc}") from exc

    payload: dict[str, object] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            payload = parsed
    except ValueError:
        pass

    if response.status_code >= 400:
        error = str(payload.get("error", response.status_code))
        if error == "invalid_grant":
            raise NotConnected("your Google account is no longer connected; connect it again")
        raise GoogleError(f"Google refused the request: {error}")
    return payload


def _email_from(payload: dict[str, object]) -> str:
    """The address out of the id token, without verifying its signature.

    Safe to read unverified *here and only here*: this token came back over TLS from
    Google's own endpoint in response to a request carrying the client secret, so there is
    no third party between the two to forge it. It is a label for the settings screen, not
    an authentication — the person is already signed in by their own session cookie.
    """
    id_token = payload.get("id_token")
    if not isinstance(id_token, str):
        return "(unknown)"
    try:
        import base64
        import json

        body = id_token.split(".")[1]
        padded = body + "=" * (-len(body) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        return str(claims.get("email", "(unknown)"))
    except Exception:  # pragma: no cover - a malformed id token is not worth a branch
        return "(unknown)"


def _fernet() -> Fernet:
    cfg = get_settings()
    if cfg.google_token_key is None:
        raise ConfigError("GOOGLE_TOKEN_KEY is not set; no Google account can be connected")
    try:
        return Fernet(cfg.google_token_key.get_secret_value())
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"GOOGLE_TOKEN_KEY is not a valid Fernet key: {exc}") from exc


def _client() -> tuple[str, str]:
    """The client id and secret, or `ConfigError`.

    Returns them rather than the settings object so the two callers below need no `assert`
    to convince a type checker that a deployment which `configured()` accepted has them.
    """
    cfg = get_settings()
    if not configured() or cfg.google_client_id is None or cfg.google_client_secret is None:
        raise ConfigError(
            "this deployment has no Google client configured; "
            "set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_TOKEN_KEY"
        )
    return cfg.google_client_id, cfg.google_client_secret.get_secret_value()


def _redirect_uri() -> str:
    """Where Google sends the person back. Must match the client's registered uri exactly."""
    return f"{get_settings().public_base_url.rstrip('/')}{CALLBACK_PATH}"


def _state_key(state: str) -> str:
    return f"mycel:google:state:{state}"
