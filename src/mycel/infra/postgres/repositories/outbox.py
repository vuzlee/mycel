from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import Outbox
from mycel.infra.postgres.repositories._sql import rowcount


class OutboxRepository:
    """Jobs waiting to reach the broker, on a caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self, job_id: str, body: dict[str, Any], headers: dict[str, Any] | None = None
    ) -> None:
        self._session.add(Outbox(job_id=job_id, body=body, headers=headers))
        await self._session.flush()

    async def mark_published(self, job_id: str) -> None:
        await self._session.execute(
            update(Outbox).where(Outbox.job_id == job_id).values(published_at=func.now())
        )

    async def unpublished(
        self, older_than: timedelta, limit: int
    ) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
        """Bodies and headers the request never published, locked so a relay skips them."""
        rows = await self._session.scalars(
            select(Outbox)
            .where(Outbox.published_at.is_(None), Outbox.created_at < func.now() - older_than)
            .order_by(Outbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [(row.body, row.headers) for row in rows]

    async def prune(self, older_than: timedelta) -> int:
        result = await self._session.execute(
            delete(Outbox).where(
                Outbox.published_at.is_not(None), Outbox.published_at < func.now() - older_than
            )
        )
        return rowcount(result)
