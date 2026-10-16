"""app.user.google_sub; app.user.password_hash and app.password_reset dropped: sign-in is
Google or an emailed code, so there is no password left to store or reset

Revision ID: 0027
Revises: 0026
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user", sa.Column("google_sub", sa.String(255), nullable=True), schema="app")
    op.create_unique_constraint("uq_user_google_sub", "user", ["google_sub"], schema="app")
    op.drop_column("user", "password_hash", schema="app")
    op.drop_index("ix_password_reset_user", table_name="password_reset", schema="app")
    op.drop_table("password_reset", schema="app")


def downgrade() -> None:
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
    # Restored empty: nobody can sign in with a password again until they set one.
    op.add_column(
        "user",
        sa.Column("password_hash", sa.Text(), nullable=False, server_default=""),
        schema="app",
    )
    op.alter_column("user", "password_hash", server_default=None, schema="app")
    op.drop_constraint("uq_user_google_sub", "user", schema="app")
    op.drop_column("user", "google_sub", schema="app")
