"""Call one connector in sources/, write the original payload down to bronze."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.logging import get_logger
from mycel.infra.postgres.models import JiraIssue
from mycel.infra.postgres.repositories.bronze import BronzeRepository
from mycel.sources import jira

#: Distinguishes "no argument" from an explicit None, which means read everything.
_UNSET: datetime = datetime.min

log = get_logger(__name__)

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

    issues = await jira.search_issues(auth, _jql(since))
    stored = await bronze.save_issues(issues)

    keys = [str(i["key"]) for i in issues if i.get("key")]
    logged = 0
    for key in keys:
        logged += await bronze.save_worklogs(key, await jira.issue_worklogs(auth, key))

    log.info(
        "fetched into bronze", extra={"issues": stored, "worklogs": logged, "since": str(since)}
    )
    return FetchResult(issues=stored, worklogs=logged, keys=keys)


def _jql(since: datetime | None) -> str:
    """Which issues to ask for: everything the service account may browse, since a time."""
    if since is None:
        return "ORDER BY updated ASC"
    return f'updated >= "{since.strftime(JQL_STAMP)}" ORDER BY updated ASC'


async def _watermark(session: AsyncSession) -> datetime | None:
    """When bronze last heard from Jira. None on an empty table, meaning read everything."""
    stamp: datetime | None = await session.scalar(select(func.max(JiraIssue.fetched_at)))
    return stamp
