"""app.jira_account: one person's consent to read and write Jira as themselves

Revision ID: 0014
Revises: 0013

Until this table, Jira was reached on one API token in `.env` — the deployment's own. That
is adequate while the app only reads: everyone sees the same board, and nobody's name is
recorded anywhere. It stops being adequate the moment the app writes. A comment posted on
a shared token appears under the host's name whatever the person typing it is called, and
Jira has no way to correct the author of an event already written.

So the grant is per person, and the table is `google_account`'s twin — one row per user,
the refresh token encrypted before it arrives, no access token column because one lives
under an hour.

**`is_syncer` is the column that is not about OAuth.** Background syncing has nobody signed
in, so it borrows one person's token; the first person to connect takes that role. The
partial unique index is the rule: at most one row may be true. A `CHECK` could not say it —
it is a statement about the table, not about a row.

`last_sync_at` exists for `core/doctor.py` alone. A syncer who leaves the company takes
the syncing with them, silently, and a dashboard going stale looks exactly like a quiet
week. This column is what lets one command tell those apart.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jira_account",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app.user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(254), nullable=False),
        sa.Column("cloud_id", sa.String(64), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("is_syncer", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    # At most one syncer. Partial, so the many `false` rows do not collide with each other.
    op.create_index(
        "uq_jira_account_syncer",
        "jira_account",
        ["is_syncer"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("is_syncer"),
    )


def downgrade() -> None:
    op.drop_index("uq_jira_account_syncer", table_name="jira_account", schema="app")
    op.drop_table("jira_account", schema="app")
