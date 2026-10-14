from collections.abc import Sequence
from dataclasses import asdict, fields
from typing import Any, TypeVar

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

RowT = TypeVar("RowT")

#: asyncpg refuses a statement with more bind parameters than this.
MAX_PARAMS = 32767


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
    dicts = [asdict(row) for row in rows]
    for chunk in chunks(dicts):
        stmt = insert(table).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint=constraint,
            set_={
                name: getattr(stmt.excluded, name)
                for name in chunk[0]
                if name not in ("source", key)
            },
        )
        await session.execute(stmt)
    return len(rows)


def chunks(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Rows split so no one multi-row INSERT passes asyncpg's parameter limit."""
    if not rows:
        return []
    size = MAX_PARAMS // len(rows[0])
    return [rows[i : i + size] for i in range(0, len(rows), size)]
