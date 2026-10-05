"""The sync runs on a service account: the syncer role goes, its record moves to the deployment

Revision ID: 0017
Revises: 0016

Batch 069. Background reads used one person's Jira token, chosen as "the first to connect",
and when they last succeeded was stamped on their row. The sync now runs on the
deployment's service account, so the role and its stamp leave `jira_account` and the
record of the last run becomes one row of its own. Hand grants in `membership` are cleared:
access is now refreshed from Jira, per person, on connect and after every sync.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_jira_account_syncer", table_name="jira_account", schema="app")
    op.drop_column("jira_account", "is_syncer", schema="app")
    op.drop_column("jira_account", "last_sync_at", schema="app")
    op.create_table(
        "sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_sync_state_one_row"),
        schema="app",
    )
    # Every grant so far was made by hand or by migration 0007; none of them came from
    # Jira. Kept, a person removed from a project in Jira would still read it here.
    op.execute("DELETE FROM app.membership")


def downgrade() -> None:
    op.drop_table("sync_state", schema="app")
    op.add_column(
        "jira_account",
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.add_column(
        "jira_account",
        sa.Column("is_syncer", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="app",
    )
    op.create_index(
        "uq_jira_account_syncer",
        "jira_account",
        ["is_syncer"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("is_syncer"),
    )
