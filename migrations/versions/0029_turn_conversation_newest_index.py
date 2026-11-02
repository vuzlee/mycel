"""app.turn index on (conversation_id, created_at desc, id desc) include (job_id, status):
the sidebar's newest-turn status read every turn and its heap row, 541 blocks cold (note 133)

Revision ID: 0029
Revises: 0028
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Concurrently: a million turns, and the api keeps writing them during a rollout.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_turn_conversation_newest ON app.turn "
            "(conversation_id, created_at DESC, id DESC) INCLUDE (job_id, status)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS app.ix_turn_conversation_newest")
