"""gold.progress_update: reported_at becomes sent_at

Revision ID: 0003
Revises: 0002

One instant carried two names. `etl/progress.py` wrote `reported_at=message.sent_at` —
the same value as silver's, renamed on the way through, so a query joining the two layers
read as though it touched two different clocks.

A column that survives a transform unchanged keeps its name. What gold adds is `status`
and `task`, both genuinely new; the timestamp is not.

RENAME, not drop-and-add: the values are already correct, and gold is rebuilt from silver
but bronze is not rebuildable at all — Telegram drops an update after 24 hours.
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
