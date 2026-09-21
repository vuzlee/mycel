"""Read bronze, write silver: the provider's envelope removed and nothing else.

All SQL for silver lives here. Silver answers to the source — a Jira field appearing or a
status being renamed changes this layer — which is what separates it from gold, where the
questions the product asks are what change.

Deduplicate on the source's natural key, not on a hash of the whole record: a provider
editing one field changes the hash and the row becomes a second row.
"""

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import SilverWorkItem, SilverWorklog
from mycel.infra.postgres.repositories.gold import WorkItemRow, WorklogRow


class SilverRepository:
    """Reads and writes silver, on a session someone else owns."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_items(self, rows: Sequence[WorkItemRow]) -> int:
        """Write work items, replacing any that share `(source, issue_key)`."""
        return await self._upsert(
            SilverWorkItem, rows, "uq_silver_work_item_natural_key", "issue_key"
        )

    async def upsert_worklogs(self, rows: Sequence[WorklogRow]) -> int:
        """Write logged entries, replacing any that share `(source, worklog_id)`."""
        return await self._upsert(
            SilverWorklog, rows, "uq_silver_worklog_natural_key", "worklog_id"
        )

    async def items(self, keys: Sequence[str] | None = None) -> list[WorkItemRow]:
        """Work items, so a promotion can read what silver actually holds.

        `keys` limits the replay to what one sync brought in. Passing nothing rebuilds
        gold from the whole layer, which is a supported operation rather than a repair.
        """
        query = self._narrow(select(SilverWorkItem), SilverWorkItem.issue_key, keys)
        result = await self._session.scalars(query.order_by(SilverWorkItem.issue_key))
        return [WorkItemRow(**_fields(row)) for row in result]

    async def worklogs(self, keys: Sequence[str] | None = None) -> list[WorklogRow]:
        """Logged entries, narrowed by the issue they belong to."""
        query = self._narrow(select(SilverWorklog), SilverWorklog.issue_key, keys)
        result = await self._session.scalars(query.order_by(SilverWorklog.worklog_id))
        return [WorklogRow(**_fields(row)) for row in result]

    async def _upsert(self, table: Any, rows: Sequence[Any], constraint: str, key: str) -> int:
        if not rows:
            return 0
        stmt = insert(table).values([asdict(row) for row in rows])
        stmt = stmt.on_conflict_do_update(
            constraint=constraint,
            set_={
                name: getattr(stmt.excluded, name)
                for name in asdict(rows[0])
                if name not in ("source", key)
            },
        )
        await self._session.execute(stmt)
        return len(rows)

    @staticmethod
    def _narrow(query: Select[Any], column: Any, keys: Sequence[str] | None) -> Select[Any]:
        return query if keys is None else query.where(column.in_(list(keys)))


def _fields(row: Any) -> dict[str, Any]:
    """A mapped row as the plain dataclass fields, without `id`.

    `id` is the table's surrogate key and means nothing outside it — the natural key is
    what callers identify a row by, and it is already in the columns.
    """
    return {
        name: getattr(row, name)
        for name in row.__table__.columns.keys()  # noqa: SIM118 — Column collection, not a dict
        if name != "id"
    }
