"""work_item.priority: the one field a board sorts by that gold never kept

Revision ID: 0010
Revises: 0009

Gold was built to answer "how far are we" and "who is over their estimate". Neither needs
a priority, so `etl/normalise.py` never asked Jira for one. The dashboard asks a third
question — "of the work that is not done, what matters most" — and that one cannot be
answered from a status category, because a category says where an item is and never how
much it is worth getting there.

A name, not a rank. One site's "Blocker" is another's "Highest", and an integer here would
be a mapping only this file knows and only the UI could undo. The order priorities are
read in is a display decision, and `PRIORITIES` in the gold repository is where it lives.

Both layers, because silver is what a replay rebuilds gold from: adding it to gold alone
would make every promotion write a null over a value the source had.

Nullable, and null is honest twice over — for every row written before this revision, and
for a site that hides the priority field, which is an ordinary configuration.
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
