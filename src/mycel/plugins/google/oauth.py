"""One person's standing permission to reach their own Google calendar."""

from dataclasses import dataclass

import httpx2

from mycel.core.config import Settings
from mycel.core.exceptions import MycelError
from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.accounts import AccountRepository, GoogleAccountRow
from mycel.infra.postgres.session import session_scope
from mycel.services import access_tokens, oauth
from mycel.services.google_signin import GOOGLE_AUTH_URL, GOOGLE_CALLBACK_PATH, GOOGLE_TOKEN_URL
from mycel.services.sealing import seal

log = get_logger(__name__)

REVOKE_URL = "https://oauth2.googleapis.com/revoke"

#: Narrowest that does the job.
SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
)

PROVIDER = "google"


class GoogleError(MycelError):
    """The consent round, or a token exchange, did not work."""


class NotConnected(GoogleError):
    """This person has no usable Google account attached."""


GOOGLE = oauth.OAuthProvider(
    key=PROVIDER,
    name="Google",
    env="GOOGLE",
    auth_url=GOOGLE_AUTH_URL,
    token_url=GOOGLE_TOKEN_URL,
    callback_path=GOOGLE_CALLBACK_PATH,
    client=lambda cfg: (cfg.google_client_id, cfg.google_client_secret),
    json_body=False,
    error=GoogleError,
    revoked=NotConnected,
    revoked_codes=("invalid_grant",),
    no_refresh_hint=("Remove Mycel at myaccount.google.com/permissions and connect again."),
)


@dataclass(frozen=True)
class Grant:
    """What came back from a consent round, ready for the repository."""

    email: str
    refresh_token: str
    scope: str


def configured(settings: Settings | None = None) -> bool:
    """Whether this deployment can connect an account at all."""
    return GOOGLE.configured(settings)


async def consent_url(user_id: int) -> str:
    """Where to send someone so Google can ask them."""
    params = {
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return await GOOGLE.consent_url(user_id, params)


async def spend_state(state: str, user_id: int) -> int:
    return await GOOGLE.owner_of(state, user_id)


async def exchange(code: str) -> Grant:
    """Turn the code Google redirected with into something worth keeping."""
    payload = await GOOGLE.code_grant(code)
    return Grant(
        email=_email_from(payload),
        refresh_token=str(payload["refresh_token"]),
        # As granted, not as asked for.
        scope=str(payload.get("scope", "")),
    )


async def _fresh(refresh_token_encrypted: str) -> access_tokens.Fresh:
    payload = await GOOGLE.refresh_grant(refresh_token_encrypted)
    return str(payload["access_token"]), access_tokens.lifetime(payload)


async def revoke(refresh_token_encrypted: str) -> None:
    """Tell Google to forget the grant. Failure is logged, never raised."""
    try:
        await oauth.post_token(REVOKE_URL, data={"token": unseal(refresh_token_encrypted)})
    except (httpx2.HTTPError, GoogleError) as exc:
        log.warning("google revoke failed", extra={"error": str(exc)})


async def connect(state: str, code: str, user_id: int) -> GoogleAccountRow:
    """Finish a consent round: check the state, exchange the code, keep the token."""
    await spend_state(state, user_id)
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
    row = await connected(user_id)
    if row is None:
        return False
    # Outside any transaction: Google can take its whole timeout to answer.
    await revoke(row.refresh_token_encrypted)
    await access_tokens.forget(PROVIDER, user_id)
    async with session_scope() as session:
        return await AccountRepository(session).delete_google_account(user_id)


async def token_for(user_id: int) -> str:
    """An access token for one person, or `NotConnected` with the sentence to show them."""
    row = await connected(user_id)
    if row is None:
        raise NotConnected("no Google account is connected; connect one in settings")
    sealed = row.refresh_token_encrypted
    return await access_tokens.cached(PROVIDER, user_id, lambda: _fresh(sealed))


def unseal(refresh_token_encrypted: str) -> str:
    return GOOGLE.unseal(refresh_token_encrypted)


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
