"""app.report becomes app.turn, and its body becomes an answer

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.report RENAME TO turn")
    op.execute("ALTER TABLE app.turn RENAME CONSTRAINT uq_report_job_id TO uq_turn_job_id")
    op.execute(
        "ALTER TABLE app.turn "
        "RENAME CONSTRAINT report_conversation_id_fkey TO turn_conversation_id_fkey"
    )
    op.execute("ALTER INDEX app.ix_report_conversation RENAME TO ix_turn_conversation")

    op.drop_column("turn", "body", schema="app")
    op.add_column("turn", sa.Column("answer", sa.Text(), nullable=True), schema="app")

    # Every thread is a chat; the column stays for a second kind later.
    op.execute("UPDATE app.conversation SET kind = 'chat' WHERE kind <> 'chat'")


def downgrade() -> None:
    op.drop_column("turn", "answer", schema="app")
    op.add_column("turn", sa.Column("body", postgresql.JSONB(), nullable=True), schema="app")

    op.execute("ALTER INDEX app.ix_turn_conversation RENAME TO ix_report_conversation")
    op.execute(
        "ALTER TABLE app.turn "
        "RENAME CONSTRAINT turn_conversation_id_fkey TO report_conversation_id_fkey"
    )
    op.execute("ALTER TABLE app.turn RENAME CONSTRAINT uq_turn_job_id TO uq_report_job_id")
    op.execute("ALTER TABLE app.turn RENAME TO report")
