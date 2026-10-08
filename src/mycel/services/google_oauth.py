"""One person's standing permission to reach their own Google calendar."""

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx2

from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError, MycelError
from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.accounts import AccountRepository, GoogleAccountRow
from mycel.infra.postgres.session import session_scope
from mycel.services import oauth
from mycel.services.tokens import TokenUnreadable, key_set, seal
from mycel.services.tokens import unseal as _unseal_token

log = get_logger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

#: Narrowest that does the job.
SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
)

CALLBACK_PATH = "/auth/google/callback"
PROVIDER = "google"
STATE_TTL_S = oauth.STATE_TTL_S


class GoogleError(MycelError):
    """The consent round, or a token exchange, did not work."""


class NotConnected(GoogleError):
    """This person has no usable Google account attached."""


@dataclass(frozen=True)
class Grant:
    """What came back from a consent round, ready for the repository."""

    email: str
    refresh_token: str
    scope: str


def configured(settings: Settings | None = None) -> bool:
    """Whether this deployment can connect an account at all."""
    cfg = settings or get_settings()
    return bool(cfg.google_client_id and cfg.google_client_secret and key_set(cfg))


async def consent_url(user_id: int) -> str:
    """Where to send someone so Google can ask them."""
    client_id, _ = _client()
    state = await oauth.start_state(PROVIDER, user_id)

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
    """Whose consent round this callback belongs to. Raises `GoogleError` if it is not one."""
    user_id = await oauth.spend_state(PROVIDER, state)
    if user_id is None:
        raise GoogleError("that consent link has expired; start again from settings")
    return user_id


async def exchange(code: str) -> Grant:
    """Turn the code Google redirected with into something worth keeping."""
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
        # As granted, not as asked for.
        scope=str(payload.get("scope", "")),
    )


async def access_token(refresh_token_encrypted: str) -> str:
    """A fresh access token for one person, from the token kept for them."""
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
    """Tell Google to forget the grant. Failure is logged, never raised."""
    try:
        await oauth.post_token(REVOKE_URL, data={"token": unseal(refresh_token_encrypted)})
    except (httpx2.HTTPError, GoogleError) as exc:
        log.warning("google revoke failed", extra={"error": str(exc)})


async def connect(state: str, code: str) -> GoogleAccountRow:
    """Finish a consent round: check the state, exchange the code, keep the token."""
    user_id = await spend_state(state)
    grant = await exchange(code)
    async with session_scope() as session:
        repo = AccountRepository(session)
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
        return await AccountRepository(session).google_account(user_id)


async def disconnect(user_id: int) -> bool:
    """Forget the grant here, and ask Google to forget it too."""
    async with session_scope() as session:
        repo = AccountRepository(session)
        row = await repo.google_account(user_id)
        if row is None:
            return False
        await revoke(row.refresh_token_encrypted)
        return await repo.delete_google_account(user_id)


async def token_for(user_id: int) -> str:
    """An access token for one person, or `NotConnected` with the sentence to show them."""
    row = await connected(user_id)
    if row is None:
        raise NotConnected("no Google account is connected; connect one in settings")
    return await access_token(row.refresh_token_encrypted)


def unseal(refresh_token_encrypted: str) -> str:
    """Decrypt a stored refresh token, phrased for the person who has to fix it."""
    try:
        return _unseal_token(refresh_token_encrypted)
    except TokenUnreadable as exc:
        raise NotConnected(
            "the stored Google token cannot be read; connect your account again"
        ) from exc


async def _token_call(data: dict[str, str]) -> dict[str, object]:
    """One POST to the token endpoint, with Google's own error text kept."""
    try:
        status, payload = await oauth.post_token(TOKEN_URL, data=data)
    except httpx2.HTTPError as exc:
        raise GoogleError(f"Google could not be reached: {exc}") from exc

    if status >= 400:
        error = str(payload.get("error", status))
        if error == "invalid_grant":
            raise NotConnected("your Google account is no longer connected; connect it again")
        raise GoogleError(f"Google refused the request: {error}")
    return payload


def _email_from(payload: dict[str, object]) -> str:
    """The address out of the id token, without verifying its signature."""
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


def _client() -> tuple[str, str]:
    """The client id and secret, or `ConfigError`."""
    cfg = get_settings()
    if not configured() or cfg.google_client_id is None or cfg.google_client_secret is None:
        raise ConfigError(
            "this deployment has no Google client configured; "
            "set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and TOKEN_ENCRYPTION_KEY"
        )
    return cfg.google_client_id, cfg.google_client_secret.get_secret_value()


def _redirect_uri() -> str:
    return oauth.redirect_uri(CALLBACK_PATH)
