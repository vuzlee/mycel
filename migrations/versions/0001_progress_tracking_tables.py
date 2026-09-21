"""bronze, silver and gold schemas: telegram_message, message, progress_update

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    op.execute("CREATE SCHEMA IF NOT EXISTS silver")
    op.execute("CREATE SCHEMA IF NOT EXISTS gold")

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

    op.create_table(
        "progress_update",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("author", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
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
    op.create_index(
        "ix_progress_update_reported_at", "progress_update", ["reported_at"], schema="gold"
    )


def downgrade() -> None:
    # Written now, while the tables are empty. Nobody writes a downgrade later.
    op.drop_index("ix_progress_update_reported_at", "progress_update", schema="gold")
    op.drop_table("progress_update", schema="gold")
    op.drop_index("ix_message_sent_at", "message", schema="silver")
    op.drop_table("message", schema="silver")
    op.drop_table("telegram_message", schema="bronze")
    op.execute("DROP SCHEMA IF EXISTS gold CASCADE")
    op.execute("DROP SCHEMA IF EXISTS silver CASCADE")
    op.execute("DROP SCHEMA IF EXISTS bronze CASCADE")
