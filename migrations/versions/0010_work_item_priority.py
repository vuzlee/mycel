"""work_item.priority: the one field a board sorts by that gold never kept

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for schema in ("silver", "gold"):
        op.add_column(
            "work_item",
            sa.Column("priority", sa.String(length=32), nullable=True),
            schema=schema,
        )


def downgrade() -> None:
    for schema in ("silver", "gold"):
        op.drop_column("work_item", "priority", schema=schema)
