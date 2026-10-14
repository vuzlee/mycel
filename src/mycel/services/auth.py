"""Register, log in, log out, and say who a cookie belongs to."""

import asyncio
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.config import get_settings
from mycel.core.exceptions import MycelError
from mycel.core.logging import get_logger
from mycel.core.principal import Principal
from mycel.infra import smtp
from mycel.infra.postgres.repositories.identity import IdentityRepository, UserRow

log = get_logger(__name__)

#: How stale `last_seen_at` may be before a request writes it again.
TOUCH_EVERY = timedelta(minutes=1)

#: How long a session lives without being renewed.
SESSION_TTL = timedelta(days=14)

#: Bytes of entropy in a session token.
TOKEN_BYTES = 32

#: Shortest password accepted.
MIN_PASSWORD = 8

#: Bytes of entropy in a reset token.
RESET_BYTES = 32

_hasher = PasswordHasher()


#: An address a reset link can reach: one `@`, something before it, a dot after it.
EMAIL_SHAPE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class AuthError(MycelError):
    """Registration or login refused. Carries no detail about which part was wrong."""


async def register(
    session: AsyncSession, email: str, password: str, invite_code: str | None = None
) -> Principal:
    """Create an account, or raise `AuthError` if it is not allowed."""
    email = _normalize(email)
    if not EMAIL_SHAPE.fullmatch(email):
        raise AuthError("that is not an email address")
    _check_allowed(email, invite_code)
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"password must be at least {MIN_PASSWORD} characters")

    repo = IdentityRepository(session)
    password_hash = await _hash(password)
    try:
        # A savepoint: a taken address undoes only this insert, not the caller's transaction.
        async with session.begin_nested():
            user = await repo.create_user(email, password_hash)
    except IntegrityError:
        raise AuthError("that email is already registered") from None
    return _principal(user)


async def authenticate(session: AsyncSession, email: str, password: str) -> Principal:
    """Check an email and password, or raise `AuthError`."""
    user = await IdentityRepository(session).user_by_email(_normalize(email))
    stored = user.password_hash if user else await _hash("no such user")

    if not await _verify(stored, password):
        raise AuthError("wrong email or password")

    if user is None:
        raise AuthError("wrong email or password")

    if _hasher.check_needs_rehash(user.password_hash):
        # The cost parameters moved on since this hash was made.
        await IdentityRepository(session).set_password_hash(user.id, await _hash(password))
    return _principal(user)


async def open_session(session: AsyncSession, user_id: int) -> str:
    """Start a session and return the cookie value and when it stops working."""
    token = secrets.token_hex(TOKEN_BYTES)
    expires_at = datetime.now(UTC) + SESSION_TTL
    await IdentityRepository(session).create_session(token, user_id, expires_at)
    return token


async def close_session(session: AsyncSession, token: str) -> None:
    """Log out. Deleting a token that is already gone is not an error."""
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

    # A write per request is a write per poll; last_seen only needs minute precision.
    if now - row.last_seen_at >= TOUCH_EVERY:
        await repo.touch_session(token, now)
    return _principal(user)


async def change_password(
    session: AsyncSession,
    user_id: int,
    current_password: str,
    new_password: str,
    keep_token: str | None = None,
) -> int:
    """Replace someone's password and end their other sessions. Returns how many ended."""
    repo = IdentityRepository(session)
    user = await repo.user_by_id(user_id)
    if user is None:
        raise AuthError("wrong password")

    if not await _verify(user.password_hash, current_password):
        raise AuthError("wrong password")

    if len(new_password) < MIN_PASSWORD:
        raise AuthError(f"password must be at least {MIN_PASSWORD} characters")

    await repo.set_password_hash(user_id, await _hash(new_password))
    return await repo.delete_sessions_for(user_id, keep=keep_token)


async def begin_password_reset(session: AsyncSession, email: str) -> "PendingMail | None":
    """Record a reset link, if that address has an account; the caller sends it after."""
    user = await IdentityRepository(session).user_by_email(_normalize(email))
    if user is None:
        return None

    token = secrets.token_urlsafe(RESET_BYTES)
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.password_reset_ttl_seconds)
    await IdentityRepository(session).create_password_reset(user.id, _digest(token), expires_at)

    minutes = settings.password_reset_ttl_seconds // 60
    link = f"{settings.public_base_url}/app/reset?token={token}"
    return PendingMail(
        user.email,
        "Reset your Mycel password",
        f"Someone asked to reset the password for this account.\n\n{link}\n\n"
        f"The link works once and stops working in {minutes} minutes. "
        "If it was not you, nothing has changed and you can ignore this.",
    )


@dataclass(frozen=True, slots=True)
class PendingMail:
    to: str
    subject: str
    body: str

    async def send(self) -> None:
        """Best effort, after the response: a failure is logged, never shown to the caller."""
        try:
            await smtp.send(self.to, self.subject, self.body)
        except Exception:
            log.warning("reset mail not sent", exc_info=True)


async def reset_password(session: AsyncSession, token: str, new_password: str) -> int:
    """Spend a reset link and set a new password. Returns how many sessions ended."""
    if len(new_password) < MIN_PASSWORD:
        raise AuthError(f"password must be at least {MIN_PASSWORD} characters")

    repo = IdentityRepository(session)
    row = await repo.password_reset_by_hash(_digest(token))
    if row is None or row.used_at is not None or row.expires_at <= datetime.now(UTC):
        raise AuthError("that reset link is no longer usable")

    # Spent under the same condition it was checked, so two clicks racing end with one winner.
    if await repo.spend_password_reset(row.id, datetime.now(UTC)) == 0:
        raise AuthError("that reset link is no longer usable")

    await repo.set_password_hash(row.user_id, await _hash(new_password))
    return await repo.delete_sessions_for(row.user_id)


async def _hash(password: str) -> str:
    """Argon2 is ~50 ms of CPU; in a thread, the loop keeps serving."""
    return await asyncio.to_thread(_hasher.hash, password)


async def _verify(stored: str, password: str) -> bool:
    try:
        return await asyncio.to_thread(_hasher.verify, stored, password)
    except (VerifyMismatchError, VerificationError):
        return False


def _digest(token: str) -> str:
    """What is stored for a reset token."""
    return hashlib.sha256(token.encode()).hexdigest()


def _check_allowed(email: str, invite_code: str | None) -> None:
    """Whether this address may register at all. Raises `AuthError` when it may not."""
    settings = get_settings()

    expected = settings.registration_invite_code
    if expected is not None and not secrets.compare_digest(
        invite_code or "", expected.get_secret_value()
    ):
        raise AuthError("registration is not open")

    domains = settings.allowed_domains
    if domains and email.rpartition("@")[2] not in domains:
        raise AuthError("registration is not open")


async def sweep_expired_sessions(session: AsyncSession) -> int:
    """Delete sessions that have already expired. Returns how many went."""
    return await IdentityRepository(session).delete_expired_sessions(datetime.now(UTC))


def _normalize(email: str) -> str:
    """One address, one spelling. Case and surrounding space are not identity."""
    return email.strip().lower()


def _principal(user: UserRow) -> Principal:
    return Principal(id=user.id, email=user.email)
