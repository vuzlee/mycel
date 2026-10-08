"""app.document.owner_id renamed user_id, like every other table in app

Revision ID: 0020
Revises: 0019

Renames only: the column, its index, its unique constraint and its foreign key. No row
is rewritten, and the downgrade renames everything back.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENAMES = (
    ("COLUMN", "owner_id", "user_id"),
    ("CONSTRAINT", "uq_document_owner_sha256", "uq_document_user_sha256"),
    ("CONSTRAINT", "document_owner_id_fkey", "document_user_id_fkey"),
)


def upgrade() -> None:
    for kind, old, new in RENAMES:
        op.execute(f"ALTER TABLE app.document RENAME {kind} {old} TO {new}")
    op.execute("ALTER INDEX app.ix_document_owner_id RENAME TO ix_document_user_id")


def downgrade() -> None:
    op.execute("ALTER INDEX app.ix_document_user_id RENAME TO ix_document_owner_id")
    for kind, old, new in reversed(RENAMES):
        op.execute(f"ALTER TABLE app.document RENAME {kind} {new} TO {old}")
