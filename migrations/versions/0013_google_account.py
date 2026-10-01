"""app.google_account: one person's consent to reach their own calendar

Revision ID: 0013
Revises: 0012

Reading somebody's calendar needs their permission, and permission that has to be asked
for on every question is permission nobody gives twice. So the refresh token is kept, and
this is the table it is kept in.

One row per user, not per grant: a second consent replaces the first rather than adding a
row, because two live grants for one person is two answers to "whose calendar" and no way
to choose. `ON CONFLICT (user_id) DO UPDATE` is what the repository writes.

**`refresh_token_encrypted`, and the name is the contract.** A refresh token opens one
person's calendar for as long as they leave it alone, so a database dump must not be a list
of calendars. Encrypted with a key from the environment — see `services/google_oauth.py`.

`scope` is stored as granted rather than as asked for. Google may hand back less than was
requested, and a tool that assumes it got what it asked for fails at the write rather than
at the connect.

No access token column. It lives fifty minutes, so storing it means a row that is stale
more often than it is useful; it is fetched when needed and held in memory.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_account",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app.user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column(
            "connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("google_account", schema="app")
