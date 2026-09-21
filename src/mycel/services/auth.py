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

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.exceptions import MycelError
from mycel.infra.postgres.repositories.app import AppRepository, UserRow

#: How long a session lives without being renewed. Two weeks: long enough that a person
#: using this daily is never asked again, short enough that a forgotten laptop expires.
SESSION_TTL = timedelta(days=14)

#: Bytes of entropy in a session token. 32 bytes is 256 bits, hex-encoded to 64 characters
#: — which is what `app.session.id` is sized for.
TOKEN_BYTES = 32

#: Shortest password accepted. A length floor is the only rule here: composition rules
#: push people towards `Password1!` and buy nothing, which is also the OWASP position.
MIN_PASSWORD = 8

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


async def register(session: AsyncSession, email: str, password: str) -> Principal:
    """Create an account, or raise `AuthError` if the address is taken.

    Registration is open — anyone who can reach the page can create an account. That is
    right for a machine on localhost and wrong for anything exposed, so exposing this
    service means revisiting this line first.
    """
    email = _normalise(email)
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


def _normalise(email: str) -> str:
    """One address, one spelling. Case and surrounding space are not identity."""
    return email.strip().lower()


def _principal(user: UserRow) -> Principal:
    return Principal(id=user.id, email=user.email)
