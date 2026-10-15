"""app.turn.tokens_in, tokens_out, duration_ms: what a turn used, for the line under it

Revision ID: 0024
Revises: 0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("tokens_in", "tokens_out", "duration_ms")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column("turn", sa.Column(name, sa.Integer(), nullable=True), schema="app")


def downgrade() -> None:
    for name in reversed(COLUMNS):
        op.drop_column("turn", name, schema="app")
