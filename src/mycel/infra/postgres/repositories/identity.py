"""People, sign-in sessions and password resets. Expiry is checked by the caller."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import (
    PasswordReset,
    Session,
    User,
)
from mycel.infra.postgres.repositories._sql import rowcount, to_row


@dataclass(frozen=True)
class UserRow:
    """A person; `password_hash` is only for `services/auth.py` and never reaches a response."""

    id: int
    email: str
    password_hash: str
    created_at: datetime


@dataclass(frozen=True)
class SessionRow:
    id: str
    user_id: int
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class PasswordResetRow:
    id: int
    user_id: int
    expires_at: datetime
    used_at: datetime | None


class IdentityRepository:
    """Reads and writes on a caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_user(self, email: str, password_hash: str) -> UserRow:
        """Add a person. Raises `IntegrityError` if the email is taken."""
        user = User(email=email, password_hash=password_hash)
        self._session.add(user)
        await self._session.flush()
        return _user(user)

    async def user_by_email(self, email: str) -> UserRow | None:
        row = await self._session.scalar(select(User).where(User.email == email))
        return _user(row) if row else None

    async def user_by_id(self, user_id: int) -> UserRow | None:
        row = await self._session.scalar(select(User).where(User.id == user_id))
        return _user(row) if row else None

    async def set_password_hash(self, user_id: int, password_hash: str) -> None:
        """Replace a stored hash, e.g. to rehash with newer cost parameters."""
        await self._session.execute(
            update(User).where(User.id == user_id).values(password_hash=password_hash)
        )

    async def create_session(self, token: str, user_id: int, expires_at: datetime) -> SessionRow:
        """Open a session under a token the caller generated."""
        row = Session(id=token, user_id=user_id, expires_at=expires_at)
        self._session.add(row)
        await self._session.flush()
        return _session(row)

    async def session_by_id(self, token: str) -> SessionRow | None:
        """The session a cookie names, expired or not."""
        row = await self._session.scalar(select(Session).where(Session.id == token))
        return _session(row) if row else None

    async def touch_session(self, token: str, at: datetime) -> None:
        """Record that the session was used. A missing row is not an error."""
        await self._session.execute(
            update(Session).where(Session.id == token).values(last_seen_at=at)
        )

    async def delete_session(self, token: str) -> None:
        await self._session.execute(delete(Session).where(Session.id == token))

    async def delete_sessions_for(self, user_id: int, keep: str | None = None) -> int:
        """Drop one person's sessions, optionally sparing the current one."""
        query = delete(Session).where(Session.user_id == user_id)
        if keep is not None:
            query = query.where(Session.id != keep)
        result = await self._session.execute(query)
        return rowcount(result)

    async def create_password_reset(
        self, user_id: int, token_hash: str, expires_at: datetime
    ) -> None:
        """Record an outstanding reset under a hash the caller made."""
        self._session.add(
            PasswordReset(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        )
        await self._session.flush()

    async def password_reset_by_hash(self, token_hash: str) -> PasswordResetRow | None:
        """The reset a hash names, spent or expired or not."""
        row = await self._session.scalar(
            select(PasswordReset).where(PasswordReset.token_hash == token_hash)
        )
        return _reset(row) if row else None

    async def spend_password_reset(self, reset_id: int, at: datetime) -> int:
        """Mark a reset used if it is not yet; returns rows changed, so one racing click wins."""
        result = await self._session.execute(
            update(PasswordReset)
            .where(PasswordReset.id == reset_id, PasswordReset.used_at.is_(None))
            .values(used_at=at)
        )
        return rowcount(result)

    async def delete_expired_sessions(self, now: datetime) -> int:
        """Delete expired sessions. Optional: expiry is also checked on read."""
        result = await self._session.execute(delete(Session).where(Session.expires_at < now))
        return rowcount(result)


def _user(row: User) -> UserRow:
    return to_row(UserRow, row)


def _session(row: Session) -> SessionRow:
    return to_row(SessionRow, row)


def _reset(row: PasswordReset) -> PasswordResetRow:
    return to_row(PasswordResetRow, row)
