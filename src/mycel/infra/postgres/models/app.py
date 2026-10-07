"""Who is using the product and what they produced.

Separate from the pipeline because its grants run the other way: an analyst may read gold
and must never read `app.user`.
"""

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
    """Someone who can log in.

    `email` is the identity and is unique; there is no separate username, because two names
    for one person is two things to keep in step for no gain.

    No plaintext password exists anywhere, not even in transit through this class:
    `services/auth.py` hashes before constructing one.
    """

    __tablename__ = "user"
    __table_args__ = ({"schema": APP},)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    """One browser, logged in, until it expires or logs out.

    The id *is* the cookie value: a long random opaque string, not a JWT. A JWT cannot be
    revoked without a server-side list of the revoked ones, which is this table with extra
    steps — so it is this table without them, and logging out deletes the row.

    `expires_at` is checked on read rather than enforced by the database, because a session
    that is one second past its expiry must read as gone even if nothing has swept it yet.
    """

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
    """Which projects one person may read.

    A row is a grant: no row, no access. That way the absent case is the closed one — a
    table of denials would make a person nobody has recorded anything about an admin.

    `project` is the key as gold spells it, not a foreign key: a project in gold is whatever
    a synced issue named, and there is no table of projects for a row to point at.
    """

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
    """One outstanding "I forgot my password" link.

    The column holds a *hash* of the token, not the token: the link is a password for as
    long as it lives, and a database someone can read must not be a list of ways in.

    `used_at` rather than a delete, so a link that arrives twice can be told from one that
    never existed — the second click is a mistake to answer clearly, not a mystery.
    """

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
    """One person's standing permission to reach their own Google calendar.

    Keyed by `user_id` rather than by an id of its own: a second consent replaces the first,
    because two live grants for one person is two answers to "whose calendar".

    The token column's name says what is in it. A refresh token opens a calendar for as
    long as nobody revokes it, so a database dump must not be a list of calendars — it is
    encrypted by `services/google_oauth.py` before it arrives here.

    No access token: it lives under an hour, which makes a stored one stale more often than
    it is useful.
    """

    __tablename__ = "google_account"
    __table_args__ = ({"schema": APP},)

    user_id: Mapped[int] = mapped_column(
        ForeignKey(f"{APP}.user.id", ondelete="CASCADE"), primary_key=True
    )
    email: Mapped[str] = mapped_column(String(254))
    refresh_token_encrypted: Mapped[str] = mapped_column(Text)
    #: As granted, not as asked for: Google may hand back less, and a tool that assumes
    #: otherwise fails at the write rather than at the connect.
    scope: Mapped[str] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class JiraAccount(Base):
    """One person's standing permission to read, and write to, Jira as themselves.

    The same shape as `GoogleAccount` and for the same reasons — one row per user, the
    token encrypted before it arrives, no access token column.

    It carries no background work. The sync runs on the deployment's service account; this
    token is used only for what is *this person's*: asking Jira which projects they may
    browse, and writing as them. `cloud_id` is which Atlassian site the grant opens.
    """

    __tablename__ = "jira_account"
    __table_args__ = {"schema": APP}

    user_id: Mapped[int] = mapped_column(
        ForeignKey(f"{APP}.user.id", ondelete="CASCADE"), primary_key=True
    )
    #: The Atlassian account id, and the display name beside it. The name is what a draft
    #: reads back, and the id is what an assignment is written with.
    account_id: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(254))
    cloud_id: Mapped[str] = mapped_column(String(64))
    refresh_token_encrypted: Mapped[str] = mapped_column(Text)
    #: As granted, not as asked for. A site may hand back less than the consent screen
    #: requested, and a tool that assumes otherwise fails at the write rather than here.
    scope: Mapped[str] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SyncState(Base):
    """How the last background sync went. One row, for the whole deployment.

    The sync belongs to no person, so neither does its record. `doctor` reads it to tell a
    sync that stopped from a week in which nothing happened — the two look the same on a
    dashboard.
    """

    __tablename__ = "sync_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_sync_state_one_row"), {"schema": APP})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Conversation(Base):
    """One conversation in the sidebar, and the turns under it.

    Replaces the browser's `localStorage` list, which could not follow a user to a second
    machine and had no way to hold anything but a job id.

    `kind` is `"chat"` for everything. Kept because a second kind of conversation is cheaper
    to add to a column that exists than to a table that has to grow one.
    """

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
    """One question and what came back, kept.

    Redis holds a result for `result_ttl_seconds` so a second process can read it; that was
    always described as a holding area rather than a record, and this is the record. The two
    coexist: Redis answers "is it done yet", this answers "what did we produce last week".

    `answer` is the markdown the orchestrator wrote. Text, not JSONB: the output has no
    schema to grow.

    `job_id` is unique so a redelivered job updates its row instead of writing a second one.

    `steps` is the tool calls this turn made, in the shape the stream sent them. Reasoning
    is not kept: it is worth watching live and not worth storing, while a tool call is what
    makes the answer checkable. Null for a turn recorded without steps.
    """

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
    # `none_as_null` because a turn that recorded nothing must write SQL NULL, not the
    # JSON literal `null` — the upsert coalesces on this column, and a JSON `null` is a
    # value, so it would overwrite the steps an earlier attempt wrote.
    steps: Mapped[list[Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
