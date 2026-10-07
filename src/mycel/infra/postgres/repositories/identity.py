"""People, their sign-in sessions and password resets, in `app`.

A row's expiry is not enforced in SQL — see `session_by_id`: the caller decides what
"expired" means.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import (
    PasswordReset,
    Session,
    User,
)


@dataclass(frozen=True)
class UserRow:
    """A person, as every layer above this one sees them.

    Carries `password_hash` because `services/auth.py` has to verify against it. Nothing
    else may look: the hash never leaves that module, and never reaches a response model.
    """

    id: int
    email: str
    password_hash: str
    created_at: datetime


@dataclass(frozen=True)
class SessionRow:
    """One logged-in browser."""

    id: str
    user_id: int
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class PasswordResetRow:
    """One outstanding reset link."""

    id: int
    user_id: int
    expires_at: datetime
    used_at: datetime | None


class IdentityRepository:
    """Reads and writes these tables on a session someone else owns, so callers can share
    one transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_user(self, email: str, password_hash: str) -> UserRow:
        """Add a person. Raises `IntegrityError` if the email is taken.

        The uniqueness check is the constraint, not a prior `SELECT`: two registrations
        racing on the same address both pass a check and only one passes the index.
        """
        user = User(email=email, password_hash=password_hash)
        self._session.add(user)
        await self._session.flush()
        return _user(user)

    async def user_by_email(self, email: str) -> UserRow | None:
        """Find someone by the address they log in with."""
        row = await self._session.scalar(select(User).where(User.email == email))
        return _user(row) if row else None

    async def user_by_id(self, user_id: int) -> UserRow | None:
        """Find someone by id."""
        row = await self._session.scalar(select(User).where(User.id == user_id))
        return _user(row) if row else None

    async def set_password_hash(self, user_id: int, password_hash: str) -> None:
        """Replace a stored hash — for a rehash onto newer cost parameters."""
        await self._session.execute(
            update(User).where(User.id == user_id).values(password_hash=password_hash)
        )

    async def create_session(self, token: str, user_id: int, expires_at: datetime) -> SessionRow:
        """Open a session under a token the caller generated.

        The token arrives already made: generating it is a security decision, and it
        belongs next to the rest of them in `services/auth.py`, not in the SQL.
        """
        row = Session(id=token, user_id=user_id, expires_at=expires_at)
        self._session.add(row)
        await self._session.flush()
        return _session(row)

    async def session_by_id(self, token: str) -> SessionRow | None:
        """The session a cookie names, expired or not.

        Deliberately does not filter on `expires_at`. An expired row and a missing one are
        the same answer to a caller, but they are not the same thing to a sweeper, and a
        repository that hides rows cannot be used to clean them up.
        """
        row = await self._session.scalar(select(Session).where(Session.id == token))
        return _session(row) if row else None

    async def touch_session(self, token: str, at: datetime) -> None:
        """Record that the session was used. Best-effort: a missing row is not an error."""
        await self._session.execute(
            update(Session).where(Session.id == token).values(last_seen_at=at)
        )

    async def delete_session(self, token: str) -> None:
        """Log out. The row goes, and with it any way to use the cookie again."""
        await self._session.execute(delete(Session).where(Session.id == token))

    async def delete_sessions_for(self, user_id: int, keep: str | None = None) -> int:
        """Drop one person's sessions, optionally sparing the one asking.

        A password change has to end every other session: the point of changing it is that
        someone else may know the old one, and a session already open does not care what
        the password is now.
        """
        query = delete(Session).where(Session.user_id == user_id)
        if keep is not None:
            query = query.where(Session.id != keep)
        result = await self._session.execute(query)
        return int(getattr(result, "rowcount", 0) or 0)

    async def create_password_reset(
        self, user_id: int, token_hash: str, expires_at: datetime
    ) -> None:
        """Record an outstanding reset. The hash arrives already made — hashing is a
        security decision and lives with the rest of them."""
        self._session.add(
            PasswordReset(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        )
        await self._session.flush()

    async def password_reset_by_hash(self, token_hash: str) -> PasswordResetRow | None:
        """The reset a link names, spent or expired or not. The caller decides what counts
        as usable, for the same reason `session_by_id` does."""
        row = await self._session.scalar(
            select(PasswordReset).where(PasswordReset.token_hash == token_hash)
        )
        return _reset(row) if row else None

    async def spend_password_reset(self, reset_id: int, at: datetime) -> int:
        """Mark a reset used, but only if it has not been. Returns how many rows changed,
        which is how two clicks racing each other end with one winner."""
        result = await self._session.execute(
            update(PasswordReset)
            .where(PasswordReset.id == reset_id, PasswordReset.used_at.is_(None))
            .values(used_at=at)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def delete_expired_sessions(self, now: datetime) -> int:
        """Sweep. Nothing depends on it running — expiry is checked on read."""
        result = await self._session.execute(delete(Session).where(Session.expires_at < now))
        return int(getattr(result, "rowcount", 0) or 0)


def _user(row: User) -> UserRow:
    return UserRow(
        id=row.id, email=row.email, password_hash=row.password_hash, created_at=row.created_at
    )


def _session(row: Session) -> SessionRow:
    return SessionRow(
        id=row.id,
        user_id=row.user_id,
        created_at=row.created_at,
        expires_at=row.expires_at,
        last_seen_at=row.last_seen_at,
    )


def _reset(row: PasswordReset) -> PasswordResetRow:
    return PasswordResetRow(
        id=row.id, user_id=row.user_id, expires_at=row.expires_at, used_at=row.used_at
    )
