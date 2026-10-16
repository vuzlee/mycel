"""Sign in with Google (OpenID Connect): only `openid email`, nothing kept from Google.

Separate from `google_oauth`, which connects Gmail and Calendar for someone already in.
Same OAuth client; its own callback, so the two rounds never take each other's state.
"""

import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import jwt

from mycel.core.config import get_settings
from mycel.core.exceptions import MycelError
from mycel.core.logging import get_logger
from mycel.infra.redis._kv import key, put, take
from mycel.infra.redis.client import get_client
from mycel.services import oauth
from mycel.services.google_oauth import AUTH_URL, TOKEN_URL

log = get_logger(__name__)

CALLBACK_PATH = "/auth/google/signin/callback"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")

_jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600)


class SignInError(MycelError):
    """The Google round did not prove who this is."""


@dataclass(frozen=True)
class Identity:
    sub: str
    email: str
    #: Where in the app to land afterwards.
    next: str


def configured() -> bool:
    """A Google client and secret are set. The token key is not needed: nothing is sealed."""
    settings = get_settings()
    return bool(settings.google_client_id and settings.google_client_secret)


async def start(hint: str | None, next_path: str | None) -> tuple[str, str]:
    """The consent URL, and the state the browser must carry back in a cookie."""
    client_id = get_settings().google_client_id
    if not configured() or client_id is None:
        raise SignInError("this deployment has no Google client")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    await put(
        await get_client(),
        _state_key(state),
        {"nonce": nonce, "next": safe_next(next_path)},
        oauth.STATE_TTL_SECONDS,
    )
    params = {
        "client_id": client_id,
        "redirect_uri": oauth.redirect_uri(CALLBACK_PATH),
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "nonce": nonce,
    }
    if hint:
        # Google skips its chooser and asks that account's password straight away.
        params["login_hint"] = hint.strip()
    else:
        params["prompt"] = "select_account"
    return f"{AUTH_URL}?{urlencode(params)}", state


async def finish(state: str, cookie_state: str | None, code: str) -> Identity:
    """Check the round, swap the code, and read a verified identity out of the id token."""
    if not cookie_state or not secrets.compare_digest(state, cookie_state):
        raise SignInError("this sign-in was started in another browser")
    stored = await take(await get_client(), _state_key(state))
    if stored is None:
        raise SignInError("this sign-in link has expired")

    settings = get_settings()
    client_id, secret = settings.google_client_id, settings.google_client_secret
    if client_id is None or secret is None:
        raise SignInError("this deployment has no Google client")
    status, payload = await oauth.post_token(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": oauth.redirect_uri(CALLBACK_PATH),
            "client_id": client_id,
            "client_secret": secret.get_secret_value(),
        },
    )
    if status >= 400 or not isinstance(payload.get("id_token"), str):
        raise SignInError(f"Google refused the sign-in: {payload.get('error', status)}")

    claims = verify(str(payload["id_token"]), client_id)
    if claims.get("nonce") != stored["nonce"]:
        raise SignInError("this sign-in does not match the one that was started")
    if claims.get("email_verified") is not True or not claims.get("email"):
        raise SignInError("Google has not verified this address")
    return Identity(sub=str(claims["sub"]), email=str(claims["email"]), next=stored["next"])


def verify(id_token: str, client_id: str) -> dict[str, object]:
    """Signature against Google's keys, then issuer, audience and expiry."""
    try:
        claims: dict[str, object] = jwt.decode(
            id_token,
            signing_key(id_token),
            algorithms=["RS256"],
            audience=client_id,
            options={"require": ["iss", "aud", "exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise SignInError(f"the Google token did not check out: {exc}") from exc
    if claims.get("iss") not in ISSUERS:
        raise SignInError("the Google token came from somewhere else")
    return claims


def signing_key(id_token: str) -> Any:
    """Google's public key for this token, from its JWKS (cached an hour)."""
    return _jwks.get_signing_key_from_jwt(id_token).key


def safe_next(next_path: str | None) -> str:
    """Only paths inside the app: anything else is an open redirect."""
    if next_path and next_path.startswith("/app/") and "//" not in next_path:
        return next_path
    return "/app/"


def _state_key(state: str) -> str:
    return key("signin", "google", state)
