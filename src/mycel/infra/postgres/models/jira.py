from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mycel.infra.postgres.models.base import BRONZE, SILVER, Base


class JiraIssue(Base):
    """One issue from `search`, stored exactly as it arrived."""

    __tablename__ = "jira_issue"
    __table_args__ = ({"schema": BRONZE},)

    issue_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    issue_key: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JiraWorklog(Base):
    """One worklog entry, as Jira returned it."""

    __tablename__ = "jira_worklog"
    __table_args__ = ({"schema": BRONZE},)

    worklog_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    issue_key: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SilverWorkItem(Base):
    """One issue, unwrapped from the provider's envelope and nothing more."""

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
    priority: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sprint_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sprint_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sprint_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
    """One worklog entry, unwrapped."""

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
