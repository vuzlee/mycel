"""app.password_reset: one outstanding reset link

Revision ID: 0008
Revises: 0007

Changing a password needed the old one, which is no help to the one person who needs it
most. This is the other half: a one-shot token, mailed to the address on the account.

The column holds a SHA-256 of the token rather than the token. A reset link is a password
for as long as it lives, and a database someone can read must not be a list of ways in.

`used_at` rather than deleting the row on use: a second click on the same link is a
mistake to answer clearly, and a missing row cannot be told from one that never existed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_reset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app.user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.create_index("ix_password_reset_user", "password_reset", ["user_id"], schema="app")


def downgrade() -> None:
    op.drop_index("ix_password_reset_user", table_name="password_reset", schema="app")
    op.drop_table("password_reset", schema="app")
