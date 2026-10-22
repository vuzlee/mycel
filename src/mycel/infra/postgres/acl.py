"""Row security on gold, enforced in the database for the role `run_sql` runs as."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mycel.infra.postgres.session import session_scope

#: The SELECT-only role `run_sql` runs as; the policies apply only to it.
READER_ROLE = "mycel_reader"

#: GUC carrying the scope; `SET LOCAL` keeps it from outliving the transaction.
SCOPE_SETTING = "mycel.projects"

_TABLES = ("work_item", "worklog")

_CREATE_ROLE = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{READER_ROLE}') THEN
        CREATE ROLE {READER_ROLE} NOLOGIN;
    END IF;
END
$$
"""


def _policy(table: str) -> list[str]:
    return [
        f"GRANT USAGE ON SCHEMA gold TO {READER_ROLE}",
        f"GRANT SELECT ON gold.{table} TO {READER_ROLE}",
        f"ALTER TABLE gold.{table} ENABLE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS {table}_granted_projects ON gold.{table}",
        # coalesce: an unset setting must deny explicitly, not via a NULL comparison.
        f"""
        CREATE POLICY {table}_granted_projects ON gold.{table}
        FOR SELECT TO {READER_ROLE}
        USING (
            project = ANY (
                string_to_array(coalesce(current_setting('{SCOPE_SETTING}', true), ''), ',')
            )
        )
        """,
    ]


#: `SET ROLE` needs membership; granted here so no superuser step is needed.
_GRANT_MEMBERSHIP = f"GRANT {READER_ROLE} TO CURRENT_USER"


def statements() -> list[str]:
    """Everything needed to put gold behind the reader role, in order."""
    return [
        _CREATE_ROLE,
        _GRANT_MEMBERSHIP,
        *[s for table in _TABLES for s in _policy(table)],
    ]


async def apply(conn: AsyncConnection) -> None:
    """Run the statements on an open connection. Idempotent."""
    for statement in statements():
        await conn.execute(text(statement))


async def scoped_read(
    query: str, params: dict[str, Any], scope: str, timeout_ms: int
) -> tuple[list[str], Sequence[Sequence[Any]]]:
    """One query in its own read-only transaction, timed out, as `READER_ROLE` within `scope`."""
    async with session_scope() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
        # Scope before role: after `SET ROLE` the scope can no longer be set.
        # `set_config` rather than `SET LOCAL` so the scope is a bind parameter.
        await session.execute(
            text("SELECT set_config(:name, :scope, true)"),
            {"name": SCOPE_SETTING, "scope": scope},
        )
        await session.execute(text(f"SET LOCAL ROLE {READER_ROLE}"))
        result = await session.execute(text(query), params)
        return list(result.keys()), result.fetchall()
