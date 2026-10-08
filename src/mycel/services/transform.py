"""Run the steps in etl/: bronze -> silver -> gold."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.logging import get_logger
from mycel.etl import normalise, promote
from mycel.infra.postgres.repositories.bronze import BronzeRepository
from mycel.infra.postgres.repositories.gold import GoldRepository
from mycel.infra.postgres.repositories.silver import SilverRepository
from mycel.services.check import check_work

log = get_logger(__name__)


@dataclass(frozen=True)
class TransformResult:
    """How much reached each layer. Reported, not just logged, so a caller can assert."""

    silver_items: int
    silver_worklogs: int
    items: int
    worklogs: int


async def transform(session: AsyncSession, keys: Sequence[str] | None = None) -> TransformResult:
    """Lift bronze into silver, then silver into gold."""
    bronze = BronzeRepository(session)

    items = [
        row
        for row in (
            normalise.from_jira_issue(payload, _project(payload))
            for payload in await bronze.issue_payloads(keys)
        )
        if row is not None
    ]
    by_key = {row.issue_key: row.project for row in items}
    worklogs = [
        row
        for row in (
            normalise.from_jira_worklog(payload, _worklog_project(payload, by_key))
            for payload in await bronze.worklog_payloads(keys)
        )
        if row is not None
    ]

    check_work(items, worklogs)

    silver = SilverRepository(session)
    silver_items = await silver.upsert_items(items)
    silver_worklogs = await silver.upsert_worklogs(worklogs)

    gold = GoldRepository(session)
    written_items = await gold.upsert_items(
        [promote.to_gold_item(row) for row in await silver.items(keys)]
    )
    written_worklogs = await gold.upsert_worklogs(
        [promote.to_gold_worklog(row) for row in await silver.worklogs(keys)]
    )

    log.info(
        "transformed",
        extra={
            "silver_items": silver_items,
            "silver_worklogs": silver_worklogs,
            "items": written_items,
            "worklogs": written_worklogs,
        },
    )
    return TransformResult(
        silver_items=silver_items,
        silver_worklogs=silver_worklogs,
        items=written_items,
        worklogs=written_worklogs,
    )


def _worklog_project(payload: dict[str, object], by_key: dict[str, str]) -> str:
    """A worklog's project: its issue's, or the issue key's prefix when the issue is not here."""
    issue = str(payload.get("issue_key", ""))
    return by_key.get(issue, issue.split("-", 1)[0])


def _project(payload: dict[str, object]) -> str:
    """The project an issue belongs to, read from the issue itself."""
    fields = payload.get("fields")
    project = fields.get("project") if isinstance(fields, dict) else None
    if isinstance(project, dict) and project.get("key"):
        return str(project["key"])
    key = str(payload.get("key", ""))
    return key.split("-", 1)[0]
