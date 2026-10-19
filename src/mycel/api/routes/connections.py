"""Connected accounts: one set of routes for every plugin, each on the person's own consent."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from mycel.api.dependencies import CurrentUser, Db, MaybeUser
from mycel.api.routes.auth import OIDC_COOKIE, finish_google_signin
from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.core.principal import Principal
from mycel.plugins import registry
from mycel.plugins.base import Plugin
from mycel.services import google_signin

router = APIRouter(prefix="/auth", tags=["connections"])

log = get_logger(__name__)


class PluginResponse(BaseModel):
    """One plugin as one person sees it."""

    key: str
    name: str
    offers: str
    configured: bool
    who: str | None = None
    since: datetime | None = None
    note: str | None = None


@router.get("/plugins", response_model=list[PluginResponse])
async def list_plugins(user: CurrentUser) -> list[PluginResponse]:
    """Every plugin, and what this person has attached to each."""
    return [await _describe(p, user) for p in registry.PLUGINS]


@router.get("/google/callback")
async def finish_google(
    user: MaybeUser,
    session: Db,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    mycel_oidc: Annotated[str | None, Cookie(alias=OIDC_COOKIE)] = None,
) -> RedirectResponse:
    """The one Google redirect uri: a sign-in or a connection, told apart by the state."""
    if google_signin.is_signin(state):
        return await finish_google_signin(session, code, state, error, mycel_oidc)
    return await _finish(_plugin("google"), user, code, state, error)


@router.get("/{key}", response_model=PluginResponse)
async def get_connection(key: str, user: CurrentUser) -> PluginResponse:
    """What this person has attached to one plugin."""
    return await _describe(_plugin(key), user)


@router.get("/{key}/start")
async def start_connection(key: str, user: CurrentUser) -> RedirectResponse:
    """Send the browser to the provider's consent screen."""
    plugin = _plugin(key)
    if not plugin.configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"this deployment has no {plugin.name} client"
        )
    return RedirectResponse(await plugin.consent_url(user.id))


@router.get("/{key}/callback")
async def finish_connection(
    key: str,
    user: MaybeUser,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Where the provider sends the browser back."""
    return await _finish(_plugin(key), user, code, state, error)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(key: str, user: CurrentUser) -> None:
    """Disconnect."""
    removed = await _plugin(key).disconnect(user.id)
    log.info(f"{key} account disconnected", extra={"user_id": user.id, "removed": removed})


def _plugin(key: str) -> Plugin:
    plugin = registry.get(key)
    if plugin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no plugin named {key}")
    return plugin


async def _describe(plugin: Plugin, user: Principal) -> PluginResponse:
    s = await plugin.status(user)
    return PluginResponse(
        key=plugin.key,
        name=plugin.name,
        offers=plugin.offers,
        configured=s.configured,
        who=s.who,
        since=s.since,
        note=s.note,
    )


async def _finish(
    plugin: Plugin,
    user: Principal | None,
    code: str | None,
    state: str | None,
    error: str | None,
) -> RedirectResponse:
    """The end of a consent round, the same for every plugin: always a redirect.

    Only the account that started the round may finish it, or a link sent to someone else
    would attach their account to the sender's.
    """
    key = plugin.key
    if error or not code or not state:
        return _back(f"{key}_error={error or 'cancelled'}")
    if user is None:
        return _back(f"{key}_error=signed_out")
    try:
        await plugin.connect(state, code, user.id)
    except Exception:  # any failure must still redirect to a readable page
        log.warning(f"{key} connect failed", exc_info=True)
        return _back(f"{key}_error=failed")
    log.info(f"{key} account connected", extra={"user_id": user.id})
    return _back(f"{key}=connected")


def _back(outcome: str) -> RedirectResponse:
    """Back to the app, carrying what happened."""
    base = get_settings().public_base_url.rstrip("/")
    return RedirectResponse(f"{base}/app/home?{outcome}")
