"""app.model_pref, app.user.default_model_ref, app.turn.model_ref: which model answers

Revision ID: 0023
Revises: 0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user", sa.Column("default_model_ref", sa.String(200), nullable=True), schema="app"
    )
    op.create_table(
        "model_pref",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app.user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model_ref", sa.String(200), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        schema="app",
    )
    op.add_column("turn", sa.Column("model_ref", sa.String(200), nullable=True), schema="app")


def downgrade() -> None:
    op.drop_column("turn", "model_ref", schema="app")
    op.drop_table("model_pref", schema="app")
    op.drop_column("user", "default_model_ref", schema="app")
