"""gold behind a reader role: the model's own SQL, filtered by Postgres

Revision ID: 0012
Revises: 0011

`run_sql` hands the model a `SELECT` against `gold.work_item` and runs whatever comes back.
Until now that read every project in the database, whoever was asking — the permission
check that `POST /reports/summary` used to do had no counterpart in a tool, and batch 033
made the tool the only way in.

IT CANNOT BE FIXED BY READING THE SQL. A project can be named in a join, a CTE, a subquery,
or not named at all by `SELECT *`. A pattern that catches today's phrasings is a pattern
the next model writes around, and it fails open when it misses.

So the filter is a row-level security policy, and the thing it applies to is a role. RLS is
bypassed by a table's owner, and the application connects as the owner because it also
writes — so gold carries a policy that applies to `mycel_reader` and to nobody else, and
`run_sql` steps into that role for the length of one transaction. Sync, `gather_progress`
and the dashboard keep reading as the owner and are untouched; they check a layer up.

UNSET MEANS NOTHING, NOT EVERYTHING. The scope arrives in `mycel.projects`, and unset reads
as the empty list. A transaction that becomes the reader without scoping itself gets no
rows. The other direction would make every forgotten scope a silent leak.

The statements live in `infra/postgres/acl.py`, not in this file: the test suite builds its
schema from `Base.metadata` and never runs alembic, so one definition has to serve both.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

from mycel.infra.postgres.acl import READER_ROLE, statements

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for statement in statements():
        op.execute(text(statement))


def downgrade() -> None:
    for table in ("work_item", "worklog"):
        op.execute(text(f"DROP POLICY IF EXISTS {table}_granted_projects ON gold.{table}"))
        op.execute(text(f"ALTER TABLE gold.{table} DISABLE ROW LEVEL SECURITY"))
        op.execute(text(f"REVOKE ALL ON gold.{table} FROM {READER_ROLE}"))
    # The role itself stays. Dropping it fails while any object still depends on it, and a
    # role with nothing granted to it is harmless.
