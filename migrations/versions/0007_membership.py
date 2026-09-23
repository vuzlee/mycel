"""app.membership: which projects a person may read

Revision ID: 0007
Revises: 0006

`services/permission.py` has always had the right call site and no rule — every place that
reads one project's data asks it first, and it answered `True` for anyone logged in. That
is correct for one team on one machine and wrong for the first deployment with two.

A row is a grant. No row, no access: the absent case has to be the closed one, or a person
nobody has recorded anything about is an administrator.

**Every existing user is granted every project this database already knows about.** An
empty table would lock out the people using the deployment at the moment it upgrades, which
is a migration that breaks the product to make it stricter. New projects and new users get
nothing by default, which is the rule from here on.

`project` is a plain column, not a foreign key. A project in gold is whatever a synced
issue named it; there is no table of projects for a row to point at.
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

    # Everyone who is already here keeps what they already had. Only for projects that
    # exist today: a project synced tomorrow is granted deliberately or not at all.
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
