"""Row security on gold, and the one role that is subject to it.

The model writes its own SQL. No amount of reading that SQL tells you which rows it will
touch, so the filter cannot live in the tool — it lives here, in the database, where a
query has no way around it.

**A separate role, not a policy on everybody.** Row-level security is bypassed by a table's
owner, and the application connects as the owner because it also writes. So gold carries a
policy that applies to `mycel_reader` and to nothing else, and `agents/tools/query.py` steps
into that role for the length of one transaction. Sync, `gather_progress` and the dashboard
keep reading as the owner and are untouched — they do their own checking a layer up.

**The policy denies when it is not told anything.** `mycel.projects` unset reads as the
empty list, so a transaction that becomes the reader role without scoping itself gets no
rows at all. The other way round — unset meaning "everything" — would turn every forgotten
scope into a silent leak, which is the failure this whole batch exists to remove.

**A deployment that ran `migrations/grants.sql` needs one more thing from that file.** RLS
is bypassed by the owner and nobody else, and there `mycel_app` is not the owner — so gold
would read as empty for sync, the dashboard and the board alike. `grants.sql` gives
`mycel_app` an unconditional read policy and membership of `mycel_reader`. The narrow role
is the one the policy binds; the application role is unrestricted on purpose, because every
other reader checks permission a layer up in `services/permission.py`.

Written as statements rather than a migration body because the test suite builds its schema
from `Base.metadata` and never runs alembic: one definition, applied from both places.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

#: The role `run_sql` runs as. Owns nothing, may only SELECT, and is the only role the
#: policies below apply to.
READER_ROLE = "mycel_reader"

#: The setting that carries the scope. A GUC rather than a temp table: `SET LOCAL` dies with
#: the transaction, so a scope cannot outlive the query it was set for.
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
        # `current_setting(..., true)` returns NULL when unset; `coalesce` turns that into
        # an empty list rather than a NULL comparison, which would be neither true nor
        # false and read as a deny by accident rather than on purpose.
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


#: The application connects as the owner of gold, and `SET ROLE` only works towards a role
#: you are a member of. Granted here so the same statements work on a fresh database and on
#: a developer's own, without a superuser step nobody would remember.
_GRANT_MEMBERSHIP = f"GRANT {READER_ROLE} TO CURRENT_USER"


def statements() -> list[str]:
    """Everything needed to put gold behind the reader role, in order."""
    return [
        _CREATE_ROLE,
        _GRANT_MEMBERSHIP,
        *[s for table in _TABLES for s in _policy(table)],
    ]


async def apply(conn: AsyncConnection) -> None:
    """Run the lot against an open connection. Idempotent, so a re-run is not an error."""
    for statement in statements():
        await conn.execute(text(statement))
