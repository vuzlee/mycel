"""app.conversation.pinned_at: a thread kept at the top of the sidebar

Revision ID: 0019
Revises: 0018

A timestamp rather than a boolean: pinned threads sort by when they were pinned, so the
newest pin sits first, and null means not pinned.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation",
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("conversation", "pinned_at", schema="app")
