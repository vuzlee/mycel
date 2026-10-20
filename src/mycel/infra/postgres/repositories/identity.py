"""People and their sign-in sessions. Expiry is checked by the caller."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import Session, User
from mycel.infra.postgres.repositories._sql import rowcount, to_row


@dataclass(frozen=True)
class UserRow:
    id: int
    email: str
    created_at: datetime
    google_sub: str | None = None


@dataclass(frozen=True)
class SessionRow:
    id: str
    user_id: int
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime


class IdentityRepository:
    """Reads and writes on a caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_user(self, email: str, google_sub: str | None = None) -> UserRow:
        """Add a person. Raises `IntegrityError` if the email or Google id is taken."""
        user = User(email=email, google_sub=google_sub)
        self._session.add(user)
        await self._session.flush()
        return _user(user)

    async def user_by_email(self, email: str) -> UserRow | None:
        row = await self._session.scalar(select(User).where(User.email == email))
        return _user(row) if row else None

    async def user_by_id(self, user_id: int) -> UserRow | None:
        row = await self._session.scalar(select(User).where(User.id == user_id))
        return _user(row) if row else None

    async def user_by_google_sub(self, google_sub: str) -> UserRow | None:
        row = await self._session.scalar(select(User).where(User.google_sub == google_sub))
        return _user(row) if row else None

    async def link_google(self, user_id: int, google_sub: str) -> None:
        """Remember which Google account this person signs in with."""
        await self._session.execute(
            update(User).where(User.id == user_id).values(google_sub=google_sub)
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

    async def session_with_user(self, token: str) -> tuple[SessionRow, UserRow] | None:
        """A cookie's session and its user in one round trip."""
        found = (
            await self._session.execute(
                select(Session, User)
                .join(User, User.id == Session.user_id)
                .where(Session.id == token)
            )
        ).first()
        return None if found is None else (_session(found[0]), _user(found[1]))

    async def touch_session(
        self, token: str, at: datetime, expires_at: datetime | None = None
    ) -> None:
        """Record that the session was used, and push its end out. A missing row is not an error."""
        values: dict[str, datetime] = {"last_seen_at": at}
        if expires_at is not None:
            values["expires_at"] = expires_at
        await self._session.execute(update(Session).where(Session.id == token).values(**values))

    async def delete_session(self, token: str) -> None:
        await self._session.execute(delete(Session).where(Session.id == token))

    async def delete_expired_sessions(self, now: datetime) -> int:
        """Delete expired sessions. Optional: expiry is also checked on read."""
        result = await self._session.execute(delete(Session).where(Session.expires_at < now))
        return rowcount(result)


def _user(row: User) -> UserRow:
    return to_row(UserRow, row)


def _session(row: Session) -> SessionRow:
    return to_row(SessionRow, row)
