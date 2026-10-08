"""Shared builders and fixtures for the Postgres tests."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.ext.asyncio import create_async_engine

from mycel.etl.normalize import JIRA
from mycel.infra.postgres.engine import async_dsn
from mycel.infra.postgres.repositories.accounts import AccountRepository
from mycel.infra.postgres.repositories.conversations import ConversationRepository
from mycel.infra.postgres.repositories.gold import WORKDAY_SECONDS, WorkItemRow, WorklogRow
from mycel.infra.postgres.repositories.gold import GoldRepository as GoldWrites
from mycel.infra.postgres.repositories.gold_stats import GoldStats
from mycel.infra.postgres.repositories.identity import IdentityRepository
from tests.fakes import DSN, SCHEMAS


class GoldRepository(GoldWrites, GoldStats):
    """Gold writes and counts on one session, so one test can write and then count."""


class AppRepository(IdentityRepository, AccountRepository, ConversationRepository):
    """All three `app` repositories on one session, so one test can mix them."""


_PG = PGDialect()  # type: ignore[no-untyped-call]


PROJECT = "MYC"


async def _drop(conn: Any) -> None:
    for schema in SCHEMAS:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


@pytest.fixture
async def alembic() -> AsyncIterator[Config]:
    """Alembic against an empty database, whatever the last run left behind."""
    engine = create_async_engine(async_dsn(DSN))
    async with engine.begin() as conn:
        await _drop(conn)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()

    yield Config("alembic.ini")

    engine = create_async_engine(async_dsn(DSN))
    async with engine.begin() as conn:
        await _drop(conn)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()


def _at(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=UTC)


def _item(key: str = "MYC-7", **kw: Any) -> WorkItemRow:
    fields: dict[str, Any] = {
        "source": JIRA,
        "project": PROJECT,
        "issue_id": key.split("-")[-1],
        "issue_key": key,
        "kind": "story",
        "parent_key": "MYC-6",
        "title": "Postgres schemas and alembic migrations",
        "status": "In Progress",
        "status_category": "doing",
        "priority": "Medium",
        "sprint_id": None,
        "sprint_name": None,
        "sprint_state": None,
        "assignee_account_id": "acct-1",
        "assignee_name": "Dev One",
        "original_estimate_seconds": 2 * WORKDAY_SECONDS,
        "time_spent_seconds": WORKDAY_SECONDS,
        "due_at": None,
        "created_at": _at(14),
        "resolved_at": None,
        "labels": ["backfill"],
        "updated_at": _at(18),
    }
    return WorkItemRow(**{**fields, **kw})


def _epic(key: str = "MYC-6", **kw: Any) -> WorkItemRow:
    return _item(key, kind="epic", parent_key=None, title="Pipeline and storage", **kw)


def _worklog(worklog_id: str = "10100", **kw: Any) -> WorklogRow:
    fields: dict[str, Any] = {
        "source": JIRA,
        "project": PROJECT,
        "worklog_id": worklog_id,
        "issue_key": "MYC-7",
        "author_account_id": "acct-1",
        "author_name": "Dev One",
        "time_spent_seconds": 5 * 3600,
        "started_at": _at(16),
        "comment": None,
    }
    return WorklogRow(**{**fields, **kw})


def _payload(key: str = "MYC-7", **overrides: Any) -> dict[str, Any]:
    """A search result, trimmed to the fields the normalizer reads."""
    fields: dict[str, Any] = {
        "summary": "Postgres schemas and alembic migrations",
        "issuetype": {"name": "Story"},
        "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
        "parent": {"key": "MYC-6"},
        "assignee": {"accountId": "acct-1", "displayName": "Dev One"},
        "duedate": None,
        "created": "2026-09-14T09:00:00.000+0000",
        "resolutiondate": None,
        "updated": "2026-09-18T09:00:00.000+0000",
        "labels": ["backfill"],
        "timeoriginalestimate": 2 * WORKDAY_SECONDS,
        "timespent": WORKDAY_SECONDS,
    }
    return {"id": key.split("-")[-1], "key": key, "fields": {**fields, **overrides}}


def _worklog_payload(worklog_id: str = "10100", **overrides: Any) -> dict[str, Any]:
    return {
        "id": worklog_id,
        "author": {"accountId": "acct-1", "displayName": "Dev One"},
        "timeSpentSeconds": 5 * 3600,
        "started": "2026-09-16T09:00:00.000+0000",
        **overrides,
    }
