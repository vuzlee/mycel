"""gold behind a reader role: the model's own SQL, filtered by Postgres

Revision ID: 0012
Revises: 0011
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
    # The role stays: dropping it fails while objects depend on it.
