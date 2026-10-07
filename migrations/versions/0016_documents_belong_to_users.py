"""app.document.owner_id: one document store per user, notebooks removed

Revision ID: 0016
Revises: 0015

Knowledge moves into the chat. Every thread of a user asks every one of their
documents, so the notebook between a user and a document has no job left. Each document
takes its notebook's owner, the notebook table goes, and the duplicate check becomes
per user. Qdrant's payload was re-keyed once, after this migration, by a one-off script.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("app.user.id", ondelete="CASCADE"),
            nullable=True,
        ),
        schema="app",
    )
    op.execute(
        "UPDATE app.document d SET owner_id = n.owner_id FROM app.notebook n "
        "WHERE n.id = d.notebook_id"
    )
    # A user who uploaded the same file into two notebooks keeps the older copy only.
    op.execute(
        "DELETE FROM app.document d USING app.document e "
        "WHERE d.owner_id = e.owner_id AND d.sha256 = e.sha256 AND d.id > e.id"
    )
    op.alter_column("document", "owner_id", nullable=False, schema="app")
    op.create_index("ix_document_owner_id", "document", ["owner_id"], schema="app")
    op.drop_constraint("uq_document_notebook_sha256", "document", schema="app")
    op.create_unique_constraint(
        "uq_document_owner_sha256", "document", ["owner_id", "sha256"], schema="app"
    )
    op.drop_index(
        "ix_app_document_notebook_id", table_name="document", schema="app", if_exists=True
    )
    op.drop_column("document", "notebook_id", schema="app")
    op.drop_table("notebook", schema="app")


def downgrade() -> None:
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
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="app",
    )
    op.execute(
        "INSERT INTO app.notebook (owner_id, name) SELECT DISTINCT owner_id, 'Documents' "
        "FROM app.document"
    )
    op.add_column("document", sa.Column("notebook_id", sa.Integer(), nullable=True), schema="app")
    op.execute(
        "UPDATE app.document d SET notebook_id = n.id FROM app.notebook n "
        "WHERE n.owner_id = d.owner_id"
    )
    op.alter_column("document", "notebook_id", nullable=False, schema="app")
    op.create_foreign_key(
        "document_notebook_id_fkey",
        "document",
        "notebook",
        ["notebook_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_document_owner_sha256", "document", schema="app")
    op.create_unique_constraint(
        "uq_document_notebook_sha256", "document", ["notebook_id", "sha256"], schema="app"
    )
    op.drop_index("ix_document_owner_id", table_name="document", schema="app")
    op.drop_column("document", "owner_id", schema="app")
