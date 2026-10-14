"""app.outbox.headers: the request's trace context, so a relayed job keeps it

Revision ID: 0022
Revises: 0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outbox", sa.Column("headers", JSONB(), nullable=True), schema="app")


def downgrade() -> None:
    op.drop_column("outbox", "headers", schema="app")
