"""Users and what they produced; separate schema so analysts can read gold, never `app`."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mycel.infra.postgres.models.base import APP, Base


class User(Base):
    """Someone who can log in; `email` is the unique identity."""

    __tablename__ = "user"
    __table_args__ = ({"schema": APP},)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    """A logged-in browser; the id is the opaque cookie value, revocable by deleting the row."""

    __tablename__ = "session"
    __table_args__ = (
        Index("ix_session_user_id", "user_id"),
        {"schema": APP},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{APP}.user.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Membership(Base):
    """A grant: which projects one person may read. No row, no access."""

    __tablename__ = "membership"
    __table_args__ = (
        UniqueConstraint("user_id", "project", name="uq_membership_user_project"),
        Index("ix_membership_user", "user_id"),
        {"schema": APP},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{APP}.user.id", ondelete="CASCADE"))
    project: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasswordReset(Base):
    """An outstanding password reset; stores a hash of the token, never the token."""

    __tablename__ = "password_reset"
    __table_args__ = (
        Index("ix_password_reset_user", "user_id"),
        {"schema": APP},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{APP}.user.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GoogleAccount(Base):
    """One person's Google calendar grant, one row per user, token stored encrypted."""

    __tablename__ = "google_account"
    __table_args__ = ({"schema": APP},)

    user_id: Mapped[int] = mapped_column(
        ForeignKey(f"{APP}.user.id", ondelete="CASCADE"), primary_key=True
    )
    email: Mapped[str] = mapped_column(String(254))
    refresh_token_encrypted: Mapped[str] = mapped_column(Text)
    #: As granted, which may be less than requested.
    scope: Mapped[str] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class JiraAccount(Base):
    """One person's Jira grant, one row per user, token stored encrypted."""

    __tablename__ = "jira_account"
    __table_args__ = {"schema": APP}

    user_id: Mapped[int] = mapped_column(
        ForeignKey(f"{APP}.user.id", ondelete="CASCADE"), primary_key=True
    )
    #: Atlassian account id (used for writes) and display name (shown in drafts).
    account_id: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(254))
    cloud_id: Mapped[str] = mapped_column(String(64))
    refresh_token_encrypted: Mapped[str] = mapped_column(Text)
    #: As granted, which may be less than requested.
    scope: Mapped[str] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SyncState(Base):
    """How the last background sync went. One row for the whole deployment."""

    __tablename__ = "sync_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_sync_state_one_row"), {"schema": APP})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Conversation(Base):
    """One conversation in the sidebar."""

    __tablename__ = "conversation"
    __table_args__ = (
        Index("ix_conversation_user_created", "user_id", "created_at"),
        {"schema": APP},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{APP}.user.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Turn(Base):
    """One question and what came back, the durable record of a job."""

    __tablename__ = "turn"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_turn_job_id"),
        Index("ix_turn_conversation", "conversation_id"),
        {"schema": APP},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey(f"{APP}.conversation.id", ondelete="CASCADE")
    )
    job_id: Mapped[str] = mapped_column(String(64))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    spent_usd: Mapped[Any | None] = mapped_column(Numeric(12, 6), nullable=True)
    # NULL, not JSON null: the upsert coalesces on this column and must not wipe earlier steps.
    steps: Mapped[list[Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
