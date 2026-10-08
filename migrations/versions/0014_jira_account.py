"""app.jira_account: one person's consent to read and write Jira as themselves

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jira_account",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app.user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(254), nullable=False),
        sa.Column("cloud_id", sa.String(64), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("is_syncer", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    # At most one syncer; partial, so the many `false` rows do not collide.
    op.create_index(
        "uq_jira_account_syncer",
        "jira_account",
        ["is_syncer"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("is_syncer"),
    )


def downgrade() -> None:
    op.drop_index("uq_jira_account_syncer", table_name="jira_account", schema="app")
    op.drop_table("jira_account", schema="app")
