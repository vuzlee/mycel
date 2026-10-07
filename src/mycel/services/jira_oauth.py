"""One person's standing permission to reach Jira as themselves.

**Per-person consent, and the argument is authorship rather than security.** A deployment
token reads a board perfectly well — everyone sees the same issues and nobody's name is
written down. It writes a board badly: a comment posted on it appears under the host's
name whoever typed it, and Jira offers no way to correct the author of an event already
recorded. So reading could have stayed on one token and writing could not, and keeping two
mechanisms for one provider would be two things to configure and two ways to be broken.

**A person's token does two things, and background reading is not one of them.** It
tells Mycel which projects that person may browse (`services/access.py`), and it writes
as them. The sync runs on the deployment's service account instead: a sync carried by one
person's consent stops the day they leave, and looks like a quiet week while it does.

**Scopes are asked for narrowly, and one of them conditionally.** `manage:jira-project` is
requested only where `JIRA_ALLOW_CREATE_PROJECT` is on, so a deployment that never creates
a project never grants the right to. Asking for everything up front, in case, is how a
consent screen comes to describe an app that does not exist.

The shape of the consent round — `state` in Redis with a TTL and spent on first use, the
token exchange, the Fernet-sealed refresh token — is `services/google_oauth.py`'s.
This is the second provider through it rather than a second design.
"""

import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx2

from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError, MycelError
from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.accounts import AccountRepository, JiraAccountRow
from mycel.infra.postgres.session import session_scope
from mycel.infra.redis.client import get_client
from mycel.services.tokens import TokenUnreadable, key_set, seal, unseal

log = get_logger(__name__)

AUTH_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"
#: Jira's own "who am I", on the chosen site. Not `api.atlassian.com/me`: that one needs the
#: `read:me` scope from a second API, and answers 403 to a grant that has only Jira's.
MYSELF_URL = "https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/myself"

#: What every connection asks for. Reading is the sync and the dashboard; `read:jira-user`
#: is how "assign it to Nam" becomes an account id; `write:jira-work` covers a comment, a
#: transition and a new issue alike. `offline_access` is the one without which there is no
#: refresh token at all, and therefore no background sync.
SCOPES = (
    "read:jira-work",
    "read:jira-user",
    "write:jira-work",
    "offline_access",
)

#: Creating a project needs admin on the site, and a project created by mistake cannot be
#: removed over the API on many of them. Asked for only where the deployment has armed it.
PROJECT_SCOPE = "manage:jira-project"

CALLBACK_PATH = "/auth/jira/callback"
HTTP_TIMEOUT_S = 15.0

#: Long enough to read a consent screen, short enough that an abandoned one is gone.
STATE_TTL_S = 600


class JiraAuthError(MycelError):
    """The consent round, or a token exchange, did not work."""


class NotConnected(JiraAuthError):
    """This person has no usable Jira account attached.

    Either they never connected one, or the grant no longer works. Both are answered the
    same way — connect it again in settings — and neither is a bug, which is why the tools
    turn this into a sentence rather than letting it raise.
    """


@dataclass(frozen=True)
class Grant:
    """What came back from a consent round, ready for the repository."""

    account_id: str
    display_name: str
    cloud_id: str
    refresh_token: str
    scope: str


def scopes() -> tuple[str, ...]:
    """What this deployment asks for, which depends on one switch.

    A function rather than a constant because the answer is configuration: a deployment
    with project creation off must never have the admin scope on its consent screen.
    """
    if get_settings().jira_allow_create_project:
        return (*SCOPES, PROJECT_SCOPE)
    return SCOPES


def configured(settings: Settings | None = None) -> bool:
    """Whether this deployment can connect an account at all.

    All three: the client is who is asking, and the key is what keeps the answer secret. A
    client with no key would store a refresh token in the clear, which counts as not
    configured rather than as configured badly.
    """
    cfg = settings or get_settings()
    return bool(cfg.jira_client_id and cfg.jira_client_secret and key_set(cfg))


async def consent_url(user_id: int) -> str:
    """Where to send someone so Atlassian can ask them.

    `prompt=consent` is what returns a refresh token on a reconnect as well as on a first
    connect. Without it a second round comes back with an access token and nothing to
    store, and the account is connected in a way that stops working within the hour.
    """
    client_id, _ = _client()
    state = secrets.token_urlsafe(32)
    client = await get_client()
    await client.set(_state_key(state), str(user_id), ex=STATE_TTL_S)

    query = urlencode(
        {
            "audience": "api.atlassian.com",
            "client_id": client_id,
            "scope": " ".join(scopes()),
            "redirect_uri": _redirect_uri(),
            "state": state,
            "response_type": "code",
            "prompt": "consent",
        }
    )
    return f"{AUTH_URL}?{query}"


async def spend_state(state: str) -> int:
    """Whose consent round this callback belongs to. Raises `JiraAuthError` if it is none.

    Spent on first use: a callback url that lands in a history file or a referrer header
    cannot be replayed into a second connection.
    """
    client = await get_client()
    user_id = await client.getdel(_state_key(state))
    if user_id is None:
        raise JiraAuthError("that consent link has expired; start again from settings")
    return int(user_id)


async def exchange(code: str) -> Grant:
    """Turn the code Atlassian redirected with into something worth keeping.

    Three calls, not one, and the two extra are not optional. Atlassian's token response
    says nothing about *which site* the grant opens or *who* consented, and both are needed
    before a write can carry a name: the cloud id is in the url of every subsequent call,
    and the account id is what an assignment is written with.
    """
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
        # As granted, not as asked for: a site may hand back less, and a tool that assumes
        # otherwise fails at the write rather than at the connect.
        scope=str(payload.get("scope", "")),
    )


async def access_token(refresh_token_encrypted: str) -> str:
    """A fresh access token for one person, from the token kept for them.

    Raises `NotConnected` when Atlassian refuses the grant — the one failure that is not a
    fault: it means the person revoked access or an admin removed the app, and the answer
    is to connect again rather than to retry.

    Does not keep the rotated refresh token; `_access_for` is the caller that does.
    """
    token, _ = await _refresh(refresh_token_encrypted)
    return token


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
    """Refresh one person's grant and keep the successor, under a row lock.

    **New Atlassian apps must rotate refresh tokens.** Every refresh returns the next one
    and retires the last, so a refresh whose successor is thrown away works once and then
    leaves a dead token in the row — the sync stops a few hours later, silently.
    """
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
    """Forget the grant here, and the project access it carried. Atlassian is not told.

    Unlike Google, Atlassian publishes no revoke endpoint for a 3LO refresh token — the
    person removes the app at id.atlassian.com. The row goes either way, which is what they
    asked for; the settings screen says where to finish the job.
    """
    async with session_scope() as session:
        return await AccountRepository(session).delete_jira_account(user_id)


async def token_for(user_id: int) -> tuple[str, str]:
    """An access token and cloud id for one person, or `NotConnected` with a sentence.

    Fetched per use rather than cached: an access token lives under an hour, and a cache of
    them would be a second place a credential sits.
    """
    row = await connected(user_id)
    if row is None:
        raise NotConnected("no Jira account is connected; connect one in settings")
    return await _access_for(user_id), row.cloud_id


def _unseal(refresh_token_encrypted: str) -> str:
    """Decrypt, turning a rotated key into the sentence it means for a person."""
    try:
        return unseal(refresh_token_encrypted)
    except TokenUnreadable as exc:
        raise NotConnected(
            "the stored Jira token cannot be read; connect your account again"
        ) from exc


async def _token_call(data: dict[str, str]) -> dict[str, Any]:
    """One POST to the token endpoint, with Atlassian's own error text kept.

    The body is the only place it says *why*, and a refused grant there is the difference
    between "connect again" and "something is broken".
    """
    try:
        async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            response = await client.post(TOKEN_URL, json=data)
    except httpx2.HTTPError as exc:
        raise JiraAuthError(f"Atlassian could not be reached: {exc}") from exc

    payload: dict[str, Any] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            payload = parsed
    except ValueError:
        pass

    if response.status_code >= 400:
        error = str(payload.get("error", response.status_code))
        if error in ("invalid_grant", "unauthorized_client", "access_denied"):
            raise NotConnected("your Jira account is no longer connected; connect it again")
        raise JiraAuthError(f"Atlassian refused the request: {error}")
    return payload


async def _cloud_id(access: str) -> str:
    """Which site this grant opens.

    One grant can cover several, and the API is addressed per site, so one has to be
    chosen. The first is taken: a deployment syncs one project, and asking a person to pick
    a site before they have seen the app is a question with no context to answer it in. A
    second site is a later batch, not a silent default.
    """
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
    """Who consented: the account id a write is attributed to, and the name to show.

    The name is a label — for the settings screen, and for reading an assignment back
    before it is written. The id is the thing that identifies anybody.
    """
    me = await _api(access, MYSELF_URL.format(cloud_id=cloud_id))
    if not isinstance(me, dict):
        raise JiraAuthError("Atlassian answered with something unreadable")
    account_id = me.get("accountId")
    if not account_id:
        raise JiraAuthError("Atlassian named no account")
    return str(account_id), str(me.get("displayName") or me.get("emailAddress") or "(unknown)")


async def _api(access: str, url: str) -> Any:
    """One authorised GET during the consent round, before any account row exists."""
    try:
        async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
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
    """The client id and secret, or `ConfigError`.

    Returns them rather than the settings object so the callers need no `assert` to
    convince a type checker that a deployment `configured()` accepted has them.
    """
    cfg = get_settings()
    if not configured() or cfg.jira_client_id is None or cfg.jira_client_secret is None:
        raise ConfigError(
            "this deployment has no Jira OAuth client configured; "
            "set JIRA_CLIENT_ID, JIRA_CLIENT_SECRET and TOKEN_ENCRYPTION_KEY"
        )
    return cfg.jira_client_id, cfg.jira_client_secret.get_secret_value()


def _redirect_uri() -> str:
    """Where Atlassian sends the person back. Must match the app's callback URL exactly."""
    return f"{get_settings().public_base_url.rstrip('/')}{CALLBACK_PATH}"


def _state_key(state: str) -> str:
    return f"mycel:jira:state:{state}"
