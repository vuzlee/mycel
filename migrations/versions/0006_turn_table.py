"""app.report becomes app.turn, and its body becomes an answer

Revision ID: 0006
Revises: 0005

`/reports` was the name from when the app had a button per capability: one for a report,
one for progress, one for the dashboard. Since batch 026 the orchestrator routes a question
to whichever specialist covers it, and since 027 there is one chat box. The table outlived
the product it was named for.

`turn` is not a new word. The HTTP layer has said it since batch 031 — `GET
/conversations/{id}/turns` returns `TurnResponse` — so this is the storage layer catching
up to a name already chosen, not a name invented here.

**`body JSONB` becomes `answer TEXT`, and that is a drop, not a cast.** The orchestrator's
output stopped being a schema in this batch: it writes markdown, and JSONB was only there
so a finding could grow an attribute without a migration. There is no cast from
`{"findings": [...], "gaps": [...]}` to the prose a model would have written for the same
question, and inventing one would put made-up text in a column that is supposed to hold
what was actually said. The rows that had a body lose it; the questions and the job ids
stay. On this deployment that is one row.

RENAME for the table, its constraints and its index, because those carry no data and a
rename keeps every row. `downgrade` reverses all of it and gives `body` back as an empty
column — the same shape, without the answers, for the same reason.
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

    # Every thread is a chat now: the one other kind was opened by `POST /reports/summary`,
    # deleted in this batch. The column stays — a second kind of thread is cheaper to add
    # to a column that exists.
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
