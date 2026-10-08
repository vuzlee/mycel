"""The sync runs on a service account: the syncer role goes, its record moves to the deployment

Revision ID: 0017
Revises: 0016
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
    # Hand grants go, or a person removed in Jira would still read the project.
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
