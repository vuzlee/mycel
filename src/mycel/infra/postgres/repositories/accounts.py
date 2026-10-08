"""Connected Google and Jira accounts, project memberships and sync state."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import (
    GoogleAccount,
    JiraAccount,
    Membership,
    SyncState,
)
from mycel.infra.postgres.repositories._sql import rowcount, to_row


@dataclass(frozen=True)
class GoogleAccountRow:
    """One person's connected Google account, token still encrypted."""

    user_id: int
    email: str
    refresh_token_encrypted: str
    scope: str
    connected_at: datetime


@dataclass(frozen=True, slots=True)
class SyncStateRow:
    """How the last background sync went. All `None` before the first run."""

    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None


@dataclass(frozen=True)
class JiraAccountRow:
    """One person's connected Jira account, token still encrypted."""

    user_id: int
    account_id: str
    display_name: str
    cloud_id: str
    refresh_token_encrypted: str
    scope: str
    connected_at: datetime


class AccountRepository:
    """Reads and writes on a caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def projects_for(self, user_id: int) -> frozenset[str]:
        """Which projects this person has been granted. Absent means none, not all."""
        rows = await self._session.scalars(
            select(Membership.project).where(Membership.user_id == user_id)
        )
        return frozenset(rows)

    async def replace_projects(self, user_id: int, projects: Iterable[str]) -> None:
        """Replace this person's grants with exactly `projects`, so lost projects are removed."""
        await self._session.execute(delete(Membership).where(Membership.user_id == user_id))
        rows = [{"user_id": user_id, "project": p} for p in sorted(set(projects))]
        if rows:
            await self._session.execute(insert(Membership).values(rows))

    async def jira_connected_users(self) -> list[int]:
        """Everyone with a Jira grant, whose access a sync refreshes."""
        rows = await self._session.scalars(
            select(JiraAccount.user_id).order_by(JiraAccount.user_id)
        )
        return list(rows)

    async def upsert_google_account(
        self, user_id: int, email: str, refresh_token_encrypted: str, scope: str
    ) -> None:
        """Attach a Google account, replacing any previous one."""
        stmt = insert(GoogleAccount).values(
            user_id=user_id,
            email=email,
            refresh_token_encrypted=refresh_token_encrypted,
            scope=scope,
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[GoogleAccount.user_id],
                set_={
                    "email": stmt.excluded.email,
                    "refresh_token_encrypted": stmt.excluded.refresh_token_encrypted,
                    "scope": stmt.excluded.scope,
                    "connected_at": func.now(),
                },
            )
        )

    async def google_account(self, user_id: int) -> GoogleAccountRow | None:
        """What this person connected, or `None`."""
        row = await self._session.scalar(
            select(GoogleAccount).where(GoogleAccount.user_id == user_id)
        )
        return _google(row) if row else None

    async def delete_google_account(self, user_id: int) -> bool:
        """Disconnect. False when there was nothing to disconnect."""
        result = await self._session.execute(
            delete(GoogleAccount).where(GoogleAccount.user_id == user_id)
        )
        return bool(rowcount(result))

    async def upsert_jira_account(
        self,
        user_id: int,
        account_id: str,
        display_name: str,
        cloud_id: str,
        refresh_token_encrypted: str,
        scope: str,
    ) -> None:
        """Attach a Jira account, replacing any previous one."""
        stmt = insert(JiraAccount).values(
            user_id=user_id,
            account_id=account_id,
            display_name=display_name,
            cloud_id=cloud_id,
            refresh_token_encrypted=refresh_token_encrypted,
            scope=scope,
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[JiraAccount.user_id],
                set_={
                    "account_id": stmt.excluded.account_id,
                    "display_name": stmt.excluded.display_name,
                    "cloud_id": stmt.excluded.cloud_id,
                    "refresh_token_encrypted": stmt.excluded.refresh_token_encrypted,
                    "scope": stmt.excluded.scope,
                    "connected_at": func.now(),
                },
            )
        )

    async def jira_account(self, user_id: int) -> JiraAccountRow | None:
        """What this person connected, or `None`."""
        row = await self._session.scalar(select(JiraAccount).where(JiraAccount.user_id == user_id))
        return _jira(row) if row else None

    async def jira_account_locked(self, user_id: int) -> JiraAccountRow | None:
        """The row, locked until commit, so two refreshes can't spend one rotating token."""
        row = await self._session.scalar(
            select(JiraAccount).where(JiraAccount.user_id == user_id).with_for_update()
        )
        return _jira(row) if row else None

    async def set_jira_refresh_token(self, user_id: int, sealed: str) -> None:
        """Store the rotated refresh token."""
        await self._session.execute(
            update(JiraAccount)
            .where(JiraAccount.user_id == user_id)
            .values(refresh_token_encrypted=sealed)
        )

    async def sync_state(self) -> SyncStateRow:
        row = await self._session.get(SyncState, 1)
        if row is None:
            return SyncStateRow(None, None, None)
        return SyncStateRow(row.last_success_at, row.last_failure_at, row.last_error)

    async def record_sync(self, at: datetime, error: str | None = None) -> None:
        """Stamp one run: a success clears the error, a failure keeps the last success."""
        values: dict[str, object] = (
            {"last_success_at": at, "last_error": None}
            if error is None
            else {"last_failure_at": at, "last_error": error[:2000]}
        )
        stmt = insert(SyncState).values(id=1, **values)
        await self._session.execute(
            stmt.on_conflict_do_update(index_elements=[SyncState.id], set_=values)
        )

    async def delete_jira_account(self, user_id: int) -> bool:
        """Disconnect and drop the project access from Jira. False if nothing was connected."""
        await self._session.execute(delete(Membership).where(Membership.user_id == user_id))
        result = await self._session.execute(
            delete(JiraAccount).where(JiraAccount.user_id == user_id)
        )
        return bool(rowcount(result))


def _google(row: GoogleAccount) -> GoogleAccountRow:
    return to_row(GoogleAccountRow, row)


def _jira(row: JiraAccount) -> JiraAccountRow:
    return to_row(JiraAccountRow, row)
