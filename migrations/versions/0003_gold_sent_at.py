"""gold.progress_update: reported_at becomes sent_at

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("progress_update", "reported_at", new_column_name="sent_at", schema="gold")
    op.execute(
        "ALTER INDEX gold.ix_progress_update_reported_at RENAME TO ix_progress_update_sent_at"
    )


def downgrade() -> None:
    op.execute(
        "ALTER INDEX gold.ix_progress_update_sent_at RENAME TO ix_progress_update_reported_at"
    )
    op.alter_column("progress_update", "sent_at", new_column_name="reported_at", schema="gold")
