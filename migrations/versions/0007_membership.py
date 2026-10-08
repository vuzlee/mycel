"""app.membership: which projects a person may read

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "membership",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app.user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "project", name="uq_membership_user_project"),
        schema="app",
    )
    op.create_index("ix_membership_user", "membership", ["user_id"], schema="app")

    # Existing users keep today's projects; later ones are granted explicitly.
    op.execute(
        """
        INSERT INTO app.membership (user_id, project)
        SELECT u.id, p.project
        FROM app."user" u
        CROSS JOIN (SELECT DISTINCT project FROM gold.work_item) p
        ON CONFLICT ON CONSTRAINT uq_membership_user_project DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_membership_user", table_name="membership", schema="app")
    op.drop_table("membership", schema="app")
