"""app.notebook, app.document, app.chunk: uploaded files, cut into searchable passages

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _now() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "notebook",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("app.user.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        _now(),
        schema="app",
    )
    op.create_table(
        "document",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "notebook_id",
            sa.Integer(),
            sa.ForeignKey("app.notebook.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("fail_reason", sa.String(64), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        _now(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("notebook_id", "sha256", name="uq_document_notebook_sha256"),
        sa.CheckConstraint(
            "status IN ('uploaded', 'parsing', 'ready', 'failed', 'deleting')",
            name="ck_document_status",
        ),
        schema="app",
    )
    op.create_index("ix_document_status", "document", ["status"], schema="app")
    op.create_table(
        "chunk",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("app.document.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("section_path", sa.Text(), server_default="", nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.UniqueConstraint("document_id", "ord", name="uq_chunk_document_ord"),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("chunk", schema="app")
    op.drop_index("ix_document_status", table_name="document", schema="app")
    op.drop_table("document", schema="app")
    op.drop_table("notebook", schema="app")
