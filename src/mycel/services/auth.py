"""Register, log in, log out, and say who a cookie belongs to.

Every security decision in this system is in this file: how a password is stored, how long
a session lives, and what a session token is made of. One file to read before trusting any
of them, and one file to change when an answer stops being good enough.

**Argon2id, not bcrypt.** bcrypt silently truncates at 72 bytes, so a long passphrase is
only ever its first 72 bytes and nobody finds out. Argon2id has no such edge and is what
the OWASP password-storage cheat sheet names first.

**An opaque random token, not a JWT.** Revoking a JWT needs a server-side list of the
revoked ones, which is a session table with extra steps — so this is a session table
without them, and logging out deletes the row.

**Expiry is checked here, on read.** The database holds `expires_at` and enforces nothing:
a session one second past its expiry has to read as gone even when no sweeper has run.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.config import get_settings
from mycel.core.exceptions import MycelError
from mycel.infra.postgres.repositories.app import AppRepository, UserRow
from mycel.notify import mail

#: How long a session lives without being renewed. Two weeks: long enough that a person
#: using this daily is never asked again, short enough that a forgotten laptop expires.
SESSION_TTL = timedelta(days=14)

#: Bytes of entropy in a session token. 32 bytes is 256 bits, hex-encoded to 64 characters
#: — which is what `app.session.id` is sized for.
TOKEN_BYTES = 32

#: Shortest password accepted. A length floor is the only rule here: composition rules
#: push people towards `Password1!` and buy nothing, which is also the OWASP position.
MIN_PASSWORD = 8

#: Bytes of entropy in a reset token. The same size as a session token, because it opens
#: the same door for as long as it lives.
RESET_BYTES = 32

_hasher = PasswordHasher()


class AuthError(MycelError):
    """Registration or login refused. Carries no detail about which part was wrong."""


@dataclass(frozen=True)
class Principal:
    """Who is making a request. What `Depends(current_user)` hands a route.

    Deliberately not `UserRow`: that one carries `password_hash`, and a hash that never
    leaves this module cannot be leaked into a response by a careless `model_validate`.
    """

    id: int
    email: str


async def register(
    session: AsyncSession, email: str, password: str, invite_code: str | None = None
) -> Principal:
    """Create an account, or raise `AuthError` if it is not allowed.

    Registration is open by default, which is right for one machine on localhost and wrong
    for anything reachable from outside it. Two settings close it — a domain allowlist and
    a shared invite code — and both are checked here rather than in the route, so a second
    caller cannot get in through a door the first one locked.
    """
    email = _normalise(email)
    _check_allowed(email, invite_code)
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"password must be at least {MIN_PASSWORD} characters")

    repo = AppRepository(session)
    try:
        user = await repo.create_user(email, _hasher.hash(password))
    except IntegrityError:
        await session.rollback()
        raise AuthError("that email is already registered") from None
    return _principal(user)


async def authenticate(session: AsyncSession, email: str, password: str) -> Principal:
    """Check an email and password, or raise `AuthError`.

    The same error for an unknown address and a wrong password, and the hash is verified
    even when nobody was found: telling the two apart, in the message or in how long the
    answer takes, turns this endpoint into a list of who has an account.
    """
    user = await AppRepository(session).user_by_email(_normalise(email))
    stored = user.password_hash if user else _hasher.hash("no such user")

    try:
        _hasher.verify(stored, password)
    except (VerifyMismatchError, VerificationError):
        raise AuthError("wrong email or password") from None

    if user is None:
        raise AuthError("wrong email or password")

    if _hasher.check_needs_rehash(user.password_hash):
        # The cost parameters moved on since this hash was made. Rehash now, while the
        # plaintext is in hand — there is no other moment when it will be.
        await AppRepository(session).set_password_hash(user.id, _hasher.hash(password))
    return _principal(user)


async def open_session(session: AsyncSession, user_id: int) -> tuple[str, datetime]:
    """Start a session and return the cookie value and when it stops working."""
    token = secrets.token_hex(TOKEN_BYTES)
    expires_at = datetime.now(UTC) + SESSION_TTL
    await AppRepository(session).create_session(token, user_id, expires_at)
    return token, expires_at


async def close_session(session: AsyncSession, token: str) -> None:
    """Log out. Deleting a token that is already gone is not an error."""
    await AppRepository(session).delete_session(token)


async def session_user(session: AsyncSession, token: str) -> Principal | None:
    """Who a cookie belongs to, or None if it names nothing usable.

    Expired reads as absent, and the expired row is deleted on the way past: the cookie is
    dead either way, and leaving the row behind means a sweeper has to exist.
    """
    repo = AppRepository(session)
    row = await repo.session_by_id(token)
    if row is None:
        return None

    now = datetime.now(UTC)
    if row.expires_at <= now:
        await repo.delete_session(token)
        return None

    user = await repo.user_by_id(row.user_id)
    if user is None:
        return None

    await repo.touch_session(token, now)
    return _principal(user)


async def change_password(
    session: AsyncSession,
    user_id: int,
    current_password: str,
    new_password: str,
    keep_token: str | None = None,
) -> int:
    """Replace someone's password and end their other sessions. Returns how many ended.

    The current password is required even though the caller already holds a live cookie: a
    borrowed laptop is exactly the case this protects against. Every other session goes,
    because the reason to change a password is that someone else may know the old one — and
    a session already open does not care what the password is now.
    """
    repo = AppRepository(session)
    user = await repo.user_by_id(user_id)
    if user is None:
        raise AuthError("wrong password")

    try:
        _hasher.verify(user.password_hash, current_password)
    except (VerifyMismatchError, VerificationError):
        raise AuthError("wrong password") from None

    if len(new_password) < MIN_PASSWORD:
        raise AuthError(f"password must be at least {MIN_PASSWORD} characters")

    await repo.set_password_hash(user_id, _hasher.hash(new_password))
    return await repo.delete_sessions_for(user_id, keep=keep_token)

async def begin_password_reset(session: AsyncSession, email: str) -> None:
    """Send a reset link, if that address has an account.

    Returns nothing either way, and the route answers the same either way: telling a
    stranger whether an address is registered is the same leak `authenticate` is careful
    not to be.

    The link is stored as a hash. It is a password while it lives, and a database that can
    be read must not be a list of ways in.
    """
    user = await AppRepository(session).user_by_email(_normalise(email))
    if user is None:
        return

    token = secrets.token_urlsafe(RESET_BYTES)
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.password_reset_ttl_seconds)
    await AppRepository(session).create_password_reset(user.id, _digest(token), expires_at)

    minutes = settings.password_reset_ttl_seconds // 60
    link = f"{settings.public_base_url}/app/reset?token={token}"
    await mail.send(
        user.email,
        "Reset your Mycel password",
        f"Someone asked to reset the password for this account.\n\n{link}\n\n"
        f"The link works once and stops working in {minutes} minutes. "
        "If it was not you, nothing has changed and you can ignore this.",
    )


async def reset_password(session: AsyncSession, token: str, new_password: str) -> int:
    """Spend a reset link and set a new password. Returns how many sessions ended.

    Every session goes, including the one that asked: a person resetting a password does
    not know which browsers are still logged in, and the reason to reset is that one of
    them may not be theirs.
    """
    if len(new_password) < MIN_PASSWORD:
        raise AuthError(f"password must be at least {MIN_PASSWORD} characters")

    repo = AppRepository(session)
    row = await repo.password_reset_by_hash(_digest(token))
    if row is None or row.used_at is not None or row.expires_at <= datetime.now(UTC):
        raise AuthError("that reset link is no longer usable")

    # Spent under the same condition it was checked, so two clicks racing end with one
    # winner rather than two password changes.
    if await repo.spend_password_reset(row.id, datetime.now(UTC)) == 0:
        raise AuthError("that reset link is no longer usable")

    await repo.set_password_hash(row.user_id, _hasher.hash(new_password))
    return await repo.delete_sessions_for(row.user_id)


def _digest(token: str) -> str:
    """What is stored for a reset token. SHA-256 and not Argon2: the token is 256 random
    bits, so there is no guessing to slow down, and a reset check is on a request path."""
    return hashlib.sha256(token.encode()).hexdigest()


def _check_allowed(email: str, invite_code: str | None) -> None:
    """Whether this address may register at all. Raises `AuthError` when it may not.

    The same refusal for a wrong code and a wrong domain: two different messages would let
    someone with neither work out which half they need to guess.
    """
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
    """Delete sessions that have already expired. Returns how many went.

    Nothing depends on this running — `session_user` refuses an expired row and deletes it
    on the way past. It exists so a row nobody ever reads again does not sit in the table
    forever, which is the only way `app.session` grows without bound.
    """
    return await AppRepository(session).delete_expired_sessions(datetime.now(UTC))

def _normalise(email: str) -> str:
    """One address, one spelling. Case and surrounding space are not identity."""
    return email.strip().lower()


def _principal(user: UserRow) -> Principal:
    return Principal(id=user.id, email=user.email)
