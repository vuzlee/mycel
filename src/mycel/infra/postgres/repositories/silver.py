"""Read bronze, write silver: the provider's envelope removed and nothing else."""

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import SilverWorkItem, SilverWorklog
from mycel.infra.postgres.repositories.gold import WorkItemRow, WorklogRow


class SilverRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_items(self, rows: Sequence[WorkItemRow]) -> int:
        """Upsert work items on `(source, issue_key)`."""
        return await self._upsert(
            SilverWorkItem, rows, "uq_silver_work_item_natural_key", "issue_key"
        )

    async def upsert_worklogs(self, rows: Sequence[WorklogRow]) -> int:
        """Upsert worklogs on `(source, worklog_id)`."""
        return await self._upsert(
            SilverWorklog, rows, "uq_silver_worklog_natural_key", "worklog_id"
        )

    async def items(self, keys: Sequence[str] | None = None) -> list[WorkItemRow]:
        """Silver work items; `keys` narrows to one sync, none means all."""
        query = self._narrow(select(SilverWorkItem), SilverWorkItem.issue_key, keys)
        result = await self._session.scalars(query.order_by(SilverWorkItem.issue_key))
        return [WorkItemRow(**_fields(row)) for row in result]

    async def worklogs(self, keys: Sequence[str] | None = None) -> list[WorklogRow]:
        """Worklog entries, narrowed by the issue they belong to."""
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
    """A mapped row as dataclass fields, without the surrogate `id`."""
    return {name: getattr(row, name) for name in row.__table__.columns.keys() if name != "id"}
