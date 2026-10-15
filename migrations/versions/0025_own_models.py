"""app.own_model and app.own_model_key: a person's own OpenAI-compatible models and sealed keys

Revision ID: 0025
Revises: 0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "own_model",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("app.user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("api_base", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Index("ix_own_model_owner", "owner_id"),
        schema="app",
    )
    op.create_table(
        "own_model_key",
        sa.Column(
            "own_model_id",
            sa.Integer(),
            sa.ForeignKey("app.own_model.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("key_sealed", sa.Text(), nullable=False),
        sa.Column("hint", sa.String(16), nullable=False),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("own_model_key", schema="app")
    op.drop_table("own_model", schema="app")
