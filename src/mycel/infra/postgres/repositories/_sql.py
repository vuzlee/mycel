from collections.abc import Sequence
from dataclasses import asdict, fields
from typing import Any, TypeVar

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

RowT = TypeVar("RowT")


def to_row(cls: type[RowT], row: Any) -> RowT:
    """A dataclass from an ORM row, field by field by name."""
    return cls(**{f.name: getattr(row, f.name) for f in fields(cls)})  # type: ignore[arg-type]


def rowcount(result: Any) -> int:
    """Rows a write touched; read via getattr since not every `Result` type declares it."""
    return int(getattr(result, "rowcount", 0) or 0)


async def upsert(
    session: AsyncSession, table: Any, rows: Sequence[Any], constraint: str, key: str
) -> int:
    """Insert dataclass rows, updating every column but `source` and `key` on conflict."""
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
    await session.execute(stmt)
    return len(rows)
