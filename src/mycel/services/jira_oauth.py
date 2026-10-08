"""One person's standing permission to reach Jira as themselves."""

from dataclasses import dataclass
from typing import Any

import httpx2

from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import MycelError
from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.accounts import AccountRepository, JiraAccountRow
from mycel.infra.postgres.session import session_scope
from mycel.services import oauth
from mycel.services.tokens import key_set, seal

log = get_logger(__name__)

AUTH_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"
#: Jira's own "who am I", on the chosen site.
MYSELF_URL = "https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/myself"

#: What every connection asks for.
SCOPES = (
    "read:jira-work",
    "read:jira-user",
    "write:jira-work",
    "offline_access",
)

#: Creating a project needs site admin, and a mistaken project cannot be undone.
PROJECT_SCOPE = "manage:jira-project"

CALLBACK_PATH = "/auth/jira/callback"
PROVIDER = "jira"


class JiraAuthError(MycelError):
    """The consent round, or a token exchange, did not work."""


class NotConnected(JiraAuthError):
    """This person has no usable Jira account attached."""


@dataclass(frozen=True)
class Grant:
    """What came back from a consent round, ready for the repository."""

    account_id: str
    display_name: str
    cloud_id: str
    refresh_token: str
    scope: str


def scopes() -> tuple[str, ...]:
    """What this deployment asks for, which depends on one switch."""
    if get_settings().jira_allow_create_project:
        return (*SCOPES, PROJECT_SCOPE)
    return SCOPES


def configured(settings: Settings | None = None) -> bool:
    """Whether this deployment can connect an account at all."""
    cfg = settings or get_settings()
    return bool(cfg.jira_client_id and cfg.jira_client_secret and key_set(cfg))


async def consent_url(user_id: int) -> str:
    """Where to send someone so Atlassian can ask them."""
    client_id, _ = _client()
    params = {
        "audience": "api.atlassian.com",
        "client_id": client_id,
        "scope": " ".join(scopes()),
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "prompt": "consent",
    }
    return await oauth.consent_url(PROVIDER, AUTH_URL, user_id, params)


async def spend_state(state: str) -> int:
    return await oauth.owner_of(PROVIDER, state, JiraAuthError)


async def exchange(code: str) -> Grant:
    """Turn the code Atlassian redirected with into something worth keeping."""
    client_id, client_secret = _client()
    payload = await _token_call(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": _redirect_uri(),
        }
    )

    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise JiraAuthError(
            "Atlassian returned no refresh token. Check that `offline_access` is one of "
            "the app's scopes, then connect again."
        )
    access = str(payload.get("access_token", ""))
    if not access:
        raise JiraAuthError("Atlassian returned no access token")

    cloud_id = await _cloud_id(access)
    account_id, display_name = await _whoami(access, cloud_id)
    return Grant(
        account_id=account_id,
        display_name=display_name,
        cloud_id=cloud_id,
        refresh_token=str(refresh_token),
        # As granted, not as asked for: a site may grant less.
        scope=str(payload.get("scope", "")),
    )


async def _refresh(refresh_token_encrypted: str) -> tuple[str, str | None]:
    """The access token, and the refresh token that replaces the one just spent, if any."""
    client_id, client_secret = _client()
    payload = await _token_call(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": _unseal(refresh_token_encrypted),
        }
    )
    token = payload.get("access_token")
    if not token:
        raise JiraAuthError("Atlassian returned no access token")
    rotated = payload.get("refresh_token")
    return str(token), str(rotated) if rotated else None


async def _access_for(user_id: int) -> str:
    """Refresh one person's grant and keep the successor, under a row lock."""
    async with session_scope() as session:
        repo = AccountRepository(session)
        row = await repo.jira_account_locked(user_id)
        if row is None:
            raise NotConnected("no Jira account is connected; connect one in settings")
        token, rotated = await _refresh(row.refresh_token_encrypted)
        if rotated:
            await repo.set_jira_refresh_token(user_id, seal(rotated))
    return token


async def connect(state: str, code: str) -> JiraAccountRow:
    """Finish a consent round: check the state, exchange the code, keep the token."""
    user_id = await spend_state(state)
    grant = await exchange(code)
    async with session_scope() as session:
        repo = AccountRepository(session)
        await repo.upsert_jira_account(
            user_id,
            grant.account_id,
            grant.display_name,
            grant.cloud_id,
            seal(grant.refresh_token),
            grant.scope,
        )
        row = await repo.jira_account(user_id)
    assert row is not None
    log.info("jira account connected", extra={"user_id": user_id})
    return row


async def connected(user_id: int) -> JiraAccountRow | None:
    """What this person has attached, for the settings screen. `None` is normal."""
    async with session_scope() as session:
        return await AccountRepository(session).jira_account(user_id)


async def disconnect(user_id: int) -> bool:
    """Forget the grant here, and the project access it carried. Atlassian is not told."""
    async with session_scope() as session:
        return await AccountRepository(session).delete_jira_account(user_id)


async def token_for(user_id: int) -> tuple[str, str]:
    """An access token and cloud id for one person, or `NotConnected` with a sentence."""
    row = await connected(user_id)
    if row is None:
        raise NotConnected("no Jira account is connected; connect one in settings")
    return await _access_for(user_id), row.cloud_id


def _unseal(refresh_token_encrypted: str) -> str:
    return oauth.unseal_for(refresh_token_encrypted, "Jira", NotConnected)


async def _token_call(data: dict[str, str]) -> dict[str, Any]:
    return await oauth.token_call(
        TOKEN_URL,
        data,
        as_json=True,
        name="Atlassian",
        error=JiraAuthError,
        revoked=NotConnected,
        revoked_codes=("invalid_grant", "unauthorized_client", "access_denied"),
    )


async def _cloud_id(access: str) -> str:
    """Which site this grant opens."""
    sites = await _api(access, RESOURCES_URL)
    if not isinstance(sites, list) or not sites:
        raise JiraAuthError(
            "that Atlassian account can reach no Jira site. Connect with an account that "
            "has access to the project."
        )
    first = sites[0]
    cloud_id = first.get("id") if isinstance(first, dict) else None
    if not cloud_id:
        raise JiraAuthError("Atlassian named a site with no id")
    return str(cloud_id)


async def _whoami(access: str, cloud_id: str) -> tuple[str, str]:
    """Who consented: the account id a write is attributed to, and the name to show."""
    me = await _api(access, MYSELF_URL.format(cloud_id=cloud_id))
    if not isinstance(me, dict):
        raise JiraAuthError("Atlassian answered with something unreadable")
    account_id = me.get("accountId")
    if not account_id:
        raise JiraAuthError("Atlassian named no account")
    return str(account_id), str(me.get("displayName") or me.get("emailAddress") or "(unknown)")


async def _api(access: str, url: str) -> Any:
    """One authorized GET during the consent round, before any account row exists."""
    try:
        async with httpx2.AsyncClient(timeout=oauth.HTTP_TIMEOUT_S) as client:
            response = await client.get(
                url, headers={"authorization": f"Bearer {access}", "accept": "application/json"}
            )
            response.raise_for_status()
            return response.json()
    except httpx2.HTTPError as exc:
        raise JiraAuthError(f"Atlassian could not be reached: {exc}") from exc
    except ValueError as exc:
        raise JiraAuthError("Atlassian answered with something that is not JSON") from exc


def _client() -> tuple[str, str]:
    cfg = get_settings()
    return oauth.credentials(cfg.jira_client_id, cfg.jira_client_secret, configured(), "JIRA")


def _redirect_uri() -> str:
    return oauth.redirect_uri(CALLBACK_PATH)
