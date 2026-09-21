"""Jira runs through silver: the middle layer stops being a name and becomes a step

Revision ID: 0005
Revises: 0004

`etl/normalise.py` read bronze and wrote gold, while every docstring and note claimed
bronze -> silver -> gold. Two layers wearing three layers' names. These tables are the
missing step.

They are column-for-column what `gold.work_item` and `gold.worklog` hold, and that is
expected rather than a smell: with one source, "clean as Jira gave it" and "what the app
needs" are the same set of columns. The two diverge when a second tracker lands, or when
gold grows a precomputed table — and the route has to exist before either can use it.

`silver.message` is dropped. It was built when Telegram was the source, batch 016 removed
that source, and nothing has written to it since. Batch 016 kept it on the grounds that it
was source-agnostic; that reasoning stops holding the moment silver has a live occupant,
because an empty table from a removed source sitting beside it is exactly the "which layer
is real" question this revision closes.

`downgrade` recreates `silver.message`, empty. Nothing was ever in it on this deployment,
so there is nothing to lose.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_item",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("project", sa.String(length=32), nullable=False),
        sa.Column("issue_id", sa.String(length=32), nullable=False),
        sa.Column("issue_key", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("parent_key", sa.String(length=64), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("status_category", sa.String(length=16), nullable=False),
        sa.Column("assignee_account_id", sa.String(length=128), nullable=True),
        sa.Column("assignee_name", sa.String(length=128), nullable=True),
        sa.Column("original_estimate_seconds", sa.BigInteger(), nullable=True),
        sa.Column("time_spent_seconds", sa.BigInteger(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "issue_key", name="uq_silver_work_item_natural_key"),
        schema="silver",
    )
    op.create_index(
        "ix_silver_work_item_project_updated",
        "work_item",
        ["project", "updated_at"],
        schema="silver",
    )
    op.create_index("ix_silver_work_item_due_at", "work_item", ["due_at"], schema="silver")

    op.create_table(
        "worklog",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("project", sa.String(length=32), nullable=False),
        sa.Column("worklog_id", sa.String(length=32), nullable=False),
        sa.Column("issue_key", sa.String(length=64), nullable=False),
        sa.Column("author_account_id", sa.String(length=128), nullable=True),
        sa.Column("author_name", sa.String(length=128), nullable=True),
        sa.Column("time_spent_seconds", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "worklog_id", name="uq_silver_worklog_natural_key"),
        schema="silver",
    )
    op.create_index(
        "ix_silver_worklog_project_started",
        "worklog",
        ["project", "started_at"],
        schema="silver",
    )

    op.drop_index("ix_message_sent_at", table_name="message", schema="silver")
    op.drop_table("message", schema="silver")


def downgrade() -> None:
    op.create_table(
        "message",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("author", sa.String(length=128), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "chat_id", "message_id", name="uq_message_natural_key"),
        schema="silver",
    )
    op.create_index("ix_message_sent_at", "message", ["sent_at"], schema="silver")

    op.drop_index("ix_silver_worklog_project_started", table_name="worklog", schema="silver")
    op.drop_table("worklog", schema="silver")
    op.drop_index("ix_silver_work_item_due_at", table_name="work_item", schema="silver")
    op.drop_index(
        "ix_silver_work_item_project_updated", table_name="work_item", schema="silver"
    )
    op.drop_table("work_item", schema="silver")
