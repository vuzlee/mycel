"""app.turn index on (conversation_id, updated_at), replacing the one on conversation_id:
the sidebar reads each conversation's newest turn, and the old index left a sort per row

Revision ID: 0028
Revises: 0027
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_turn_conversation_updated", "turn", ["conversation_id", "updated_at"], schema="app"
    )
    op.drop_index("ix_turn_conversation", table_name="turn", schema="app")


def downgrade() -> None:
    op.create_index("ix_turn_conversation", "turn", ["conversation_id"], schema="app")
    op.drop_index("ix_turn_conversation_updated", table_name="turn", schema="app")
