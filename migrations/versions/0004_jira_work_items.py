"""Jira becomes the source: work items and worklogs replace parsed hashtags

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jira_issue",
        sa.Column("issue_id", sa.String(length=32), nullable=False),
        sa.Column("issue_key", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("issue_id"),
        schema="bronze",
    )

    op.create_table(
        "jira_worklog",
        sa.Column("worklog_id", sa.String(length=32), nullable=False),
        sa.Column("issue_key", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("worklog_id"),
        schema="bronze",
    )

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
        sa.UniqueConstraint("source", "issue_key", name="uq_work_item_natural_key"),
        schema="gold",
    )
    op.create_index(
        "ix_work_item_project_updated", "work_item", ["project", "updated_at"], schema="gold"
    )
    op.create_index("ix_work_item_due_at", "work_item", ["due_at"], schema="gold")

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
        sa.UniqueConstraint("source", "worklog_id", name="uq_worklog_natural_key"),
        schema="gold",
    )
    op.create_index(
        "ix_worklog_project_started", "worklog", ["project", "started_at"], schema="gold"
    )

    op.drop_index("ix_progress_update_sent_at", table_name="progress_update", schema="gold")
    op.drop_table("progress_update", schema="gold")
    op.drop_table("telegram_message", schema="bronze")


def downgrade() -> None:
    op.create_table(
        "telegram_message",
        sa.Column("update_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("update_id"),
        schema="bronze",
    )

    op.create_table(
        "progress_update",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("author", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source", "chat_id", "message_id", name="uq_progress_update_natural_key"
        ),
        schema="gold",
    )
    op.create_index("ix_progress_update_sent_at", "progress_update", ["sent_at"], schema="gold")

    op.drop_index("ix_worklog_project_started", table_name="worklog", schema="gold")
    op.drop_table("worklog", schema="gold")
    op.drop_index("ix_work_item_due_at", table_name="work_item", schema="gold")
    op.drop_index("ix_work_item_project_updated", table_name="work_item", schema="gold")
    op.drop_table("work_item", schema="gold")
    op.drop_table("jira_worklog", schema="bronze")
    op.drop_table("jira_issue", schema="bronze")
