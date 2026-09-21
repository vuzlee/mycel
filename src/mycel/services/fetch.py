"""Call one connector in sources/, write the original payload down to bronze.

No processing, no cleaning — keeping the original means a bad transform can be re-run
from bronze instead of hitting the provider again.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.postgres.models import JiraIssue
from mycel.infra.postgres.repositories.bronze import BronzeRepository
from mycel.sources import jira

log = get_logger(__name__)

#: JQL date format. Minutes, because Jira's own grammar has no seconds and a window that
#: overlaps by one minute costs nothing — every write below upserts.
JQL_STAMP = "%Y-%m-%d %H:%M"


@dataclass(frozen=True)
class FetchResult:
    """What one fetch brought in, and which issues it touched.

    The keys are carried back rather than re-derived, so the transform replays exactly
    this fetch instead of the whole of bronze.
    """

    issues: int
    worklogs: int
    keys: list[str]


async def fetch_jira(session: AsyncSession) -> FetchResult:
    """Pull every issue that moved since the last sync, and its logged effort.

    The watermark is the newest `fetched_at` in bronze rather than a cursor kept
    elsewhere: what was stored *is* what was read, so the two can never drift apart. On an
    empty table there is no watermark and the whole project is read once.

    Worklogs cost one request per issue, which is why they are fetched only for the issues
    this pass brought back and not for the project each tick.
    """
    bronze = BronzeRepository(session)
    since = await _watermark(session)

    issues = await jira.search_issues(_jql(since))
    stored = await bronze.save_issues(issues)

    keys = [str(i["key"]) for i in issues if i.get("key")]
    logged = 0
    for key in keys:
        logged += await bronze.save_worklogs(key, await jira.issue_worklogs(key))

    log.info(
        "fetched into bronze", extra={"issues": stored, "worklogs": logged, "since": str(since)}
    )
    return FetchResult(issues=stored, worklogs=logged, keys=keys)


def _jql(since: datetime | None) -> str:
    """Which issues to ask for. Project first, so a shared site is not read wholesale."""
    project = get_settings().jira_project_key
    clauses = [f"project = {project}"] if project else []
    if since is not None:
        clauses.append(f'updated >= "{since.strftime(JQL_STAMP)}"')
    where = " AND ".join(clauses)
    return f"{where} ORDER BY updated ASC" if where else "ORDER BY updated ASC"


async def _watermark(session: AsyncSession) -> datetime | None:
    """When bronze last heard from Jira. None on an empty table, meaning read everything."""
    stamp: datetime | None = await session.scalar(select(func.max(JiraIssue.fetched_at)))
    return stamp
