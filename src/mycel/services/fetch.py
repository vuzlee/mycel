"""Call one connector in sources/, write the original payload down to bronze."""

import asyncio
from collections.abc import Sequence
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
UNSET: datetime = datetime.min

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
    session: AsyncSession, auth: jira.Auth, projects: Sequence[str], since: datetime | None = UNSET
) -> FetchResult:
    """Pull every issue in `projects` that moved since that project's last fetch."""
    bronze = BronzeRepository(session)
    marks = await _watermarks(session) if since is UNSET else {}
    issues: list[dict[str, Any]] = []

    async with jira_session():
        for project in projects:
            mark = since if since is not UNSET else marks.get(project)
            issues += await jira.search_issues(auth, _jql(project, mark))
        keys = [str(i["key"]) for i in issues if i.get("key")]
        worklogs = await _worklogs(auth, keys)

    stored = await bronze.save_issues(issues)
    logged = await bronze.save_all_worklogs(dict(zip(keys, worklogs, strict=True)))

    log.info(
        "fetched into bronze",
        extra={"issues": stored, "worklogs": logged, "projects": len(projects)},
    )
    return FetchResult(issues=stored, worklogs=logged, keys=keys)


async def _worklogs(auth: jira.Auth, keys: list[str]) -> list[list[dict[str, Any]]]:
    """Every issue's worklogs, read in parallel and returned in key order."""
    gate = asyncio.Semaphore(PARALLEL)

    async def one(key: str) -> list[dict[str, Any]]:
        async with gate:
            return await jira.issue_worklogs(auth, key)

    return list(await asyncio.gather(*(one(k) for k in keys)))


def _jql(project: str, since: datetime | None) -> str:
    """One project's issues, all of them or those updated since a time."""
    scope = f'project = "{project}"'
    if since is None:
        return f"{scope} ORDER BY updated ASC"
    return f'{scope} AND updated >= "{since.strftime(JQL_STAMP)}" ORDER BY updated ASC'


async def _watermarks(session: AsyncSession) -> dict[str, datetime]:
    """When bronze last heard of each project. A project absent here is read in full."""
    project = JiraIssue.payload["fields"]["project"]["key"].astext
    rows = await session.execute(select(project, func.max(JiraIssue.fetched_at)).group_by(project))
    return {str(p): stamp for p, stamp in rows.all() if p}
