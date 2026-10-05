"""Mapped tables for a user's document store: a document is cut into chunks."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from mycel.infra.postgres.models import APP, Base

UPLOADED = "uploaded"
PARSING = "parsing"
READY = "ready"
FAILED = "failed"
DELETING = "deleting"

#: While a user has a document in one of these, their knowledge base cannot be asked.
IN_FLIGHT = (UPLOADED, PARSING)


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (
        UniqueConstraint("owner_id", "sha256", name="uq_document_owner_sha256"),
        {"schema": APP},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey(f"{APP}.user.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default=UPLOADED)
    fail_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Chunk(Base):
    __tablename__ = "chunk"
    __table_args__ = (
        UniqueConstraint("document_id", "ord", name="uq_chunk_document_ord"),
        {"schema": APP},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey(f"{APP}.document.id", ondelete="CASCADE"))
    ord: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    section_path: Mapped[str] = mapped_column(Text, default="")
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens: Mapped[int] = mapped_column(Integer)
