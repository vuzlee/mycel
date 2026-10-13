"""Call one connector in sources/, write the original payload down to bronze."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.logging import get_logger
from mycel.infra.postgres.models import JiraIssue
from mycel.infra.postgres.repositories.bronze import BronzeRepository
from mycel.sources import jira
from mycel.sources.jira_http import session as jira_session

#: Distinguishes "no argument" from an explicit None, which means read everything.
_UNSET: datetime = datetime.min

log = get_logger(__name__)

#: Worklog reads in flight at once; Jira rate-limits per grant.
PARALLEL = 8

#: JQL date format.
JQL_STAMP = "%Y-%m-%d %H:%M"


@dataclass(frozen=True)
class FetchResult:
    """What one fetch brought in, and which issues it touched."""

    issues: int
    worklogs: int
    keys: list[str]


async def fetch_jira(
    session: AsyncSession, auth: jira.Auth, since: datetime | None = _UNSET
) -> FetchResult:
    """Pull every issue that moved since the last sync, and its logged effort."""
    bronze = BronzeRepository(session)
    if since is _UNSET:
        since = await _watermark(session)

    async with jira_session():
        issues = await jira.search_issues(auth, _jql(since))
        keys = [str(i["key"]) for i in issues if i.get("key")]
        worklogs = await _worklogs(auth, keys)

    stored = await bronze.save_issues(issues)
    logged = 0
    for key, entries in zip(keys, worklogs, strict=True):
        logged += await bronze.save_worklogs(key, entries)

    log.info(
        "fetched into bronze", extra={"issues": stored, "worklogs": logged, "since": str(since)}
    )
    return FetchResult(issues=stored, worklogs=logged, keys=keys)


async def _worklogs(auth: jira.Auth, keys: list[str]) -> list[list[dict[str, Any]]]:
    """Every issue's worklogs, read in parallel and returned in key order."""
    gate = asyncio.Semaphore(PARALLEL)

    async def one(key: str) -> list[dict[str, Any]]:
        async with gate:
            return await jira.issue_worklogs(auth, key)

    return list(await asyncio.gather(*(one(k) for k in keys)))


def _jql(since: datetime | None) -> str:
    """Which issues to ask for: everything the service account may browse, since a time."""
    if since is None:
        return "ORDER BY updated ASC"
    return f'updated >= "{since.strftime(JQL_STAMP)}" ORDER BY updated ASC'


async def _watermark(session: AsyncSession) -> datetime | None:
    """When bronze last heard from Jira. None on an empty table, meaning read everything."""
    stamp: datetime | None = await session.scalar(select(func.max(JiraIssue.fetched_at)))
    return stamp
