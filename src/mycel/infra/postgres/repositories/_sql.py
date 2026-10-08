from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


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
