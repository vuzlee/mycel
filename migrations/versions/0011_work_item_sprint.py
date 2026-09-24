"""work_item sprint columns: the unit a Scrum team actually plans in

Revision ID: 0011
Revises: 0010

The board answers in calendar time — this week, twelve weeks, a month per column. That is
the right axis for "was anyone working", and the wrong one for every question a Scrum team
asks out loud: what did we commit to, what did we finish, how does this sprint compare to
the last. Those are asked per sprint, and a sprint is not a fortnight of the calendar — it
starts when someone starts it and ends when someone closes it.

Three columns rather than one, all denormalised onto the item, and no `sprint` table. A
sprint has exactly three facts a board needs (its name, whether it is open, when it ran)
and they are already on every issue Jira returns, so a table would buy a join and a second
sync path to hold what the item already carries.

`sprint_id` is Jira's own integer, kept as the thing to group by: two sprints can share a
name across boards, and a name is renamed mid-flight often enough that grouping on it
would silently split a sprint in two.

THE LAST SPRINT, NOT EVERY SPRINT. Jira's field is an array — an issue rolled over from
one sprint into the next lists both, in order. These columns keep the last, which is the
one it is in *now*. That loses the rollover history, which is a real loss and the right
trade here: the question is "what is in this sprint", and an issue that appears in three
sprints at once makes every count larger than the board it describes.

Nullable throughout, and null is the ordinary case rather than a gap: the backlog is
issues with no sprint, and a team-managed project can run for a year without ever using
one.
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
    # Grouping the dashboard's sprint block is always "this project, by sprint", and
    # without this it is a sequential scan of every issue the project has ever had.
    op.create_index(
        "ix_work_item_project_sprint", "work_item", ["project", "sprint_id"], schema="gold"
    )


def downgrade() -> None:
    op.drop_index("ix_work_item_project_sprint", "work_item", schema="gold")
    for schema in ("silver", "gold"):
        for column in ("sprint_state", "sprint_name", "sprint_id"):
            op.drop_column("work_item", column, schema=schema)
