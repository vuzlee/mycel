"""work_item sprint columns: the unit a Scrum team actually plans in

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for schema in ("silver", "gold"):
        op.add_column(
            "work_item", sa.Column("sprint_id", sa.Integer(), nullable=True), schema=schema
        )
        op.add_column(
            "work_item",
            sa.Column("sprint_name", sa.String(length=128), nullable=True),
            schema=schema,
        )
        op.add_column(
            "work_item",
            sa.Column("sprint_state", sa.String(length=16), nullable=True),
            schema=schema,
        )
    # The dashboard groups by project and sprint.
    op.create_index(
        "ix_work_item_project_sprint", "work_item", ["project", "sprint_id"], schema="gold"
    )


def downgrade() -> None:
    op.drop_index("ix_work_item_project_sprint", "work_item", schema="gold")
    for schema in ("silver", "gold"):
        for column in ("sprint_state", "sprint_name", "sprint_id"):
            op.drop_column("work_item", column, schema=schema)
