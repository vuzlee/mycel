"""Run the steps in etl/: bronze -> silver -> gold.

Idempotent: re-running the same window gives the same result, because every write upserts
on a natural key.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.etl import normalise, promote
from mycel.infra.postgres.repositories.bronze import BronzeRepository
from mycel.infra.postgres.repositories.gold import GoldRepository
from mycel.infra.postgres.repositories.silver import SilverRepository
from mycel.services.check import check_work

log = get_logger(__name__)


@dataclass(frozen=True)
class TransformResult:
    """How much reached each layer. Reported, not just logged, so a caller can assert.

    The silver and gold counts are separate on purpose: with one source they must agree,
    and a test that says so is what keeps the middle layer honest rather than decorative.
    """

    silver_items: int
    silver_worklogs: int
    items: int
    worklogs: int


async def transform(session: AsyncSession, keys: Sequence[str] | None = None) -> TransformResult:
    """Lift bronze into silver, then silver into gold.

    `keys` limits the replay to the issues one fetch brought in; without it the whole of
    bronze is rebuilt, which is a supported operation rather than a repair hack.

    The checks run before the first write. Silver is the layer above bronze now, and the
    point of stopping here is that nothing malformed ever gets that far — so a failure
    leaves both silver and gold untouched, with bronze still holding everything needed to
    replay once the transform is fixed.

    Gold is promoted from what silver *holds*, read back, rather than from the rows still
    in memory. That makes `transform(session)` with no keys a genuine rebuild from silver
    instead of a rebuild from bronze wearing a different name.
    """
    bronze = BronzeRepository(session)
    project = get_settings().jira_project_key or ""

    items = [
        row
        for row in (
            normalise.from_jira_issue(payload, _project(payload, project))
            for payload in await bronze.issue_payloads(keys)
        )
        if row is not None
    ]
    by_key = {row.issue_key: row.project for row in items}
    worklogs = [
        row
        for row in (
            normalise.from_jira_worklog(payload, by_key.get(str(payload.get("issue_key")), project))
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


def _project(payload: dict[str, object], fallback: str) -> str:
    """The project an issue belongs to, taken from its key rather than from configuration.

    `JIRA_PROJECT_KEY` may be empty, meaning "every project this account can see", and in
    that case the key prefix is the only thing that says which one an issue came from.
    """
    key = str(payload.get("key", ""))
    return key.split("-", 1)[0] if "-" in key else fallback
