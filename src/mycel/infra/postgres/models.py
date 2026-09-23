"""The mapped tables. One schema per layer, so a grant can follow the layer boundary.

A gold table is a contract: agents and reports read it. Adding a column is free; changing
what an existing column means needs two releases, like any published interface.

`app` is the fourth schema and the odd one out: it holds who is using the product and what
they produced, not data flowing through the pipeline. Separate because the grants differ in
the opposite direction — an analyst role may read gold and must never read `app.user`.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

BRONZE = "bronze"
SILVER = "silver"
GOLD = "gold"
APP = "app"


class Base(DeclarativeBase):
    """Declarative base. `alembic` autogenerates against this metadata."""


class JiraIssue(Base):
    """One issue from `search`, stored exactly as it arrived.

    Nothing is parsed here on purpose. Jira keeps its own history, so unlike Telegram this
    could be re-fetched — but a re-fetch reads what the issue looks like *now*, not what it
    looked like when the transform first ran, which is a different fact. Bronze is what
    remembers the difference.

    `issue_id` rather than `issue_key` as the key: a key changes when a project is renamed
    or an issue is moved, and the id never does.
    """

    __tablename__ = "jira_issue"
    __table_args__ = ({"schema": BRONZE},)

    issue_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    issue_key: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JiraWorklog(Base):
    """One logged entry, as Jira handed it over.

    Separate from the issue because Jira serves it from a separate endpoint and because a
    worklog is the one thing in this source that can be back-dated: its `started` is
    whatever it was told, which makes it the only honest time series in a project that was
    filled in after the fact.
    """

    __tablename__ = "jira_worklog"
    __table_args__ = ({"schema": BRONZE},)

    worklog_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    issue_key: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SilverWorkItem(Base):
    """One issue, unwrapped from its provider's envelope and nothing more.

    Silver answers to the **source**: Jira adding a field or renaming a status changes
    this table. Gold answers to the **question**: a new dashboard block changes that one.
    While Jira is the only source the two hold identical columns, which is what one source
    looks like rather than a duplication to clean up — `etl/promote.py` is where they will
    diverge.

    Columns mirror `gold.work_item` exactly, down to the natural key, so the promotion
    step stays a copy until it has a reason not to be.
    """

    __tablename__ = "work_item"
    __table_args__ = (
        UniqueConstraint("source", "issue_key", name="uq_silver_work_item_natural_key"),
        Index("ix_silver_work_item_project_updated", "project", "updated_at"),
        Index("ix_silver_work_item_due_at", "due_at"),
        {"schema": SILVER},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    project: Mapped[str] = mapped_column(String(32))
    issue_id: Mapped[str] = mapped_column(String(32))
    issue_key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    parent_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64))
    status_category: Mapped[str] = mapped_column(String(16))
    assignee_account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assignee_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    original_estimate_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    time_spent_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    labels: Mapped[list[str]] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SilverWorklog(Base):
    """One logged entry, unwrapped. The silver twin of `gold.worklog`."""

    __tablename__ = "worklog"
    __table_args__ = (
        UniqueConstraint("source", "worklog_id", name="uq_silver_worklog_natural_key"),
        Index("ix_silver_worklog_project_started", "project", "started_at"),
        {"schema": SILVER},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    project: Mapped[str] = mapped_column(String(32))
    worklog_id: Mapped[str] = mapped_column(String(32))
    issue_key: Mapped[str] = mapped_column(String(64))
    author_account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    time_spent_seconds: Mapped[int] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkItem(Base):
    """One piece of tracked work: an epic, a story, a task, a subtask.

    Replaces `progress_update`, which held a hashtag and a sentence. That could say a task
    was in progress and nothing else — not whether it was late, what it was estimated at,
    or which epic it belonged to. This is the shape a question like "who is over their
    estimate" can actually be asked of.

    Field names are Jira's own wherever Jira has one, so a column here can be traced back
    to a payload in bronze without a translation table in someone's head.
    `original_estimate_seconds` and `time_spent_seconds` are seconds because that is what
    Jira stores; hours and days are a display decision and are made in the UI.

    `parent_key` is a key, not a foreign key: a sync may bring in a child before its
    parent, and a constraint would make the order of a page of results load-bearing.

    `status` is the site's own name for a status and `status_category` is Jira's
    `todo`/`doing`/`done` rollup. Both, because one team renames "In Progress" to
    "Cooking" and a dashboard still has to group it with the others.
    """

    __tablename__ = "work_item"
    __table_args__ = (
        UniqueConstraint("source", "issue_key", name="uq_work_item_natural_key"),
        Index("ix_work_item_project_updated", "project", "updated_at"),
        Index("ix_work_item_due_at", "due_at"),
        {"schema": GOLD},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    project: Mapped[str] = mapped_column(String(32))
    issue_id: Mapped[str] = mapped_column(String(32))
    issue_key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    parent_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64))
    status_category: Mapped[str] = mapped_column(String(16))
    assignee_account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assignee_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    original_estimate_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    time_spent_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    labels: Mapped[list[str]] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Worklog(Base):
    """Effort, on the day it was spent.

    One row per logged entry rather than one running total per issue, because a total
    cannot answer "how did this week go" and a curve can. Keyed by Jira's own worklog id,
    so an edited entry updates its row instead of being counted twice.
    """

    __tablename__ = "worklog"
    __table_args__ = (
        UniqueConstraint("source", "worklog_id", name="uq_worklog_natural_key"),
        Index("ix_worklog_project_started", "project", "started_at"),
        {"schema": GOLD},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    project: Mapped[str] = mapped_column(String(32))
    worklog_id: Mapped[str] = mapped_column(String(32))
    issue_key: Mapped[str] = mapped_column(String(64))
    author_account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    time_spent_seconds: Mapped[int] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


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


class Conversation(Base):
    """One thread in the sidebar, and the turns under it.

    Replaces the browser's `localStorage` list, which could not follow a user to a second
    machine and had no way to hold anything but a job id.

    `kind` is `"chat"` for everything since batch 033, when the one other kind — a progress
    summary opened by its own endpoint — was deleted along with that endpoint. Kept because
    a second kind of thread is cheaper to add to a column that exists than to a table that
    has to grow one.
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


class Turn(Base):
    """One question and what came back, kept.

    Redis holds a result for `result_ttl_seconds` so a second process can read it; that was
    always described as a holding area rather than a record, and this is the record. The two
    coexist: Redis answers "is it done yet", this answers "what did we produce last week".

    `answer` is the markdown the orchestrator wrote. It was `body JSONB` until batch 033,
    when the orchestrator's output stopped being a schema — JSONB was there so a finding
    could grow an attribute without a migration, and text needs neither.

    `job_id` is unique so a redelivered job updates its row instead of writing a second one.
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
