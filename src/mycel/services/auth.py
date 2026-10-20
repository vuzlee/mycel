"""Who someone is: the account behind a sign-in, and the session cookie that follows it."""

import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.config import get_settings
from mycel.core.exceptions import MycelError
from mycel.core.logging import get_logger
from mycel.core.principal import Principal
from mycel.infra.postgres.repositories.identity import IdentityRepository, UserRow

log = get_logger(__name__)

#: How stale `last_seen_at` may be before a request writes it again.
TOUCH_EVERY = timedelta(minutes=1)

#: How long a session lives unused; each use (at most once a minute) starts it again.
SESSION_TTL = timedelta(days=14)

#: Bytes of entropy in a session token.
TOKEN_BYTES = 32

#: An address mail can reach: one `@`, something before it, a dot after it.
EMAIL_SHAPE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class AuthError(MycelError):
    """Sign-in refused. Carries no detail about which part was wrong."""


async def account_for(
    session: AsyncSession, email: str, google_sub: str | None = None
) -> Principal:
    """The account a verified address signs into, made on first sight.

    With `google_sub`, that id wins over the address, and an account found by address is
    linked to it, so a person who signed up with a code keeps their history on Google.
    """
    email = normalize(email)
    # Every sign-in, not only the first: removing a domain must lock its accounts out too.
    check_allowed(email)
    repo = IdentityRepository(session)
    if google_sub is not None:
        found = await repo.user_by_google_sub(google_sub)
        if found is not None:
            return _principal(found)

    found = await repo.user_by_email(email)
    if found is not None:
        if google_sub is not None and found.google_sub is None:
            await repo.link_google(found.id, google_sub)
        return _principal(found)

    try:
        # A savepoint: a racing first sign-in undoes only this insert, not the caller's.
        async with session.begin_nested():
            user = await repo.create_user(email, google_sub)
    except IntegrityError:
        found = await repo.user_by_email(email)
        if found is None:
            raise AuthError("could not sign in") from None
        return _principal(found)
    log.info("user created", extra={"user_id": user.id})
    return _principal(user)


async def open_session(session: AsyncSession, user_id: int) -> str:
    """Start a session and return the cookie value."""
    token = secrets.token_hex(TOKEN_BYTES)
    expires_at = datetime.now(UTC) + SESSION_TTL
    await IdentityRepository(session).create_session(token, user_id, expires_at)
    return token


async def close_session(session: AsyncSession, token: str) -> None:
    """Sign out. Deleting a token that is already gone is not an error."""
    await IdentityRepository(session).delete_session(token)


async def session_user(session: AsyncSession, token: str) -> Principal | None:
    """Who a cookie belongs to, or None if it names nothing usable."""
    repo = IdentityRepository(session)
    found = await repo.session_with_user(token)
    if found is None:
        return None
    row, user = found

    now = datetime.now(UTC)
    if row.expires_at <= now:
        await repo.delete_session(token)
        return None

    # A write per request is a write per poll; minute precision is enough for both fields.
    if now - row.last_seen_at >= TOUCH_EVERY:
        await repo.touch_session(token, now, now + SESSION_TTL)
    return _principal(user)


async def sweep_expired_sessions(session: AsyncSession) -> int:
    """Delete sessions that have already expired. Returns how many went."""
    return await IdentityRepository(session).delete_expired_sessions(datetime.now(UTC))


def check_allowed(email: str) -> None:
    """Whether this address may have an account at all. Raises `AuthError` when not."""
    domains = get_settings().allowed_domains
    if domains and email.rpartition("@")[2] not in domains:
        raise AuthError("this address cannot sign in here")


def normalize(email: str) -> str:
    """One address, one spelling. Case and surrounding space are not identity."""
    return email.strip().lower()


def _principal(user: UserRow) -> Principal:
    return Principal(id=user.id, email=user.email)
