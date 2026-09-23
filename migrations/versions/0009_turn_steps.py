"""app.turn.steps: the tool calls a turn made, kept

Revision ID: 0009
Revises: 0008

A thread reopened after an hour showed a question, an answer and an empty middle. Agent
events lived only in a Redis Stream, capped and expiring with the result TTL, and
`infra/redis/streams.py` says why outright: an event is worth a reload, never a record.

That stays true of reasoning. It stopped being true of tool calls, which are what make an
answer checkable — "who logged the most hours" is worth trusting when the SQL that
produced it is on the page. So this keeps those and nothing else.

A column rather than a table: steps have no life of their own. They are written once with
the answer, die with the turn that already cascades, and nothing queries across turns. A
table would add a foreign key, an index and a join per turn read, paid for flexibility
nobody asked for.

JSONB holding the events in their wire shape, because the page already builds its tree
from exactly that list. A second shape here would mean a second tree builder, and two
builders drift.

Nullable, and null is the honest value for every turn that ran before this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "turn",
        sa.Column("steps", postgresql.JSONB(), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("turn", "steps", schema="app")
