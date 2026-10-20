"""Jira's sync: pull each project on a connected person's token and push it up to gold."""

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from mycel.core.exceptions import MycelError
from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.accounts import AccountRepository
from mycel.infra.postgres.repositories.bronze import BronzeRepository
from mycel.infra.postgres.session import session_scope
from mycel.observability.metrics import records_written, sync_duration_seconds
from mycel.plugins.jira import access
from mycel.plugins.jira import oauth as jira_oauth
from mycel.queue.job import Job, JobKind
from mycel.services import enqueue
from mycel.services.fetch import UNSET, FetchResult, fetch_jira
from mycel.services.transform import transform
from mycel.sources.jira import Auth

log = get_logger(__name__)


@dataclass(frozen=True)
class SyncResult:
    """One run, counted at each layer."""

    fetched: int
    silver_items: int
    silver_worklogs: int
    items: int
    worklogs: int


async def refetch_jira() -> SyncResult:
    """Read every project again, ignoring the watermarks, then transform it."""
    return await sync_jira(since=None)


async def sync_jira(since: datetime | None = UNSET) -> SyncResult:
    """Fetch on connected people's tokens, then transform what the fetch brought in."""
    started = time.monotonic()
    try:
        access_now = await access.refresh_everyone()
        last_good = await _last_success()
        fetched = await _fetch_all(readers(access_now), since)
        async with session_scope() as session:
            # Also what an earlier, failed run left in bronze: its watermark is already past it.
            left = await BronzeRepository(session).keys_fetched_since(last_good)
            result = await transform(session, keys=sorted({*fetched.keys, *left}))
    except Exception as exc:
        await _record(error=str(exc) or type(exc).__name__)
        raise

    await _queue_index()
    await _record()

    # Observed after the transform, not in a `finally`: a failed sync has no useful duration.
    sync_duration_seconds.labels(domain="jira").observe(time.monotonic() - started)
    for layer, count in (
        ("bronze", fetched.issues),
        ("silver", result.silver_items),
        ("gold", result.items),
    ):
        records_written.labels(domain="jira", layer=layer).set(count)

    log.info(
        "sync finished",
        extra={
            "fetched": fetched.issues,
            "silver_items": result.silver_items,
            "silver_worklogs": result.silver_worklogs,
            "items": result.items,
            "worklogs": result.worklogs,
            "people": len(access_now),
        },
    )
    return SyncResult(
        fetched=fetched.issues,
        silver_items=result.silver_items,
        silver_worklogs=result.silver_worklogs,
        items=result.items,
        worklogs=result.worklogs,
    )


def readers(access_now: Mapping[int, frozenset[str]]) -> dict[int, list[str]]:
    """Who reads which project: each project once, by the first person who may browse it."""
    plan: dict[int, list[str]] = {}
    taken: set[str] = set()
    for user_id in sorted(access_now):
        mine = sorted(access_now[user_id] - taken)
        if mine:
            plan[user_id] = mine
            taken.update(mine)
    return plan


async def _fetch_all(plan: Mapping[int, list[str]], since: datetime | None) -> FetchResult:
    """One fetch per reader. A reader whose token fails is skipped; the rest still sync."""
    issues = worklogs = 0
    keys: list[str] = []
    for user_id, projects in plan.items():
        try:
            token, cloud_id = await jira_oauth.token_for(user_id)
        except MycelError:
            log.warning("skipping a reader with no usable token", extra={"user_id": user_id})
            continue
        async with session_scope() as session:
            one = await fetch_jira(session, Auth(token, cloud_id), projects, since)
        issues, worklogs, keys = issues + one.issues, worklogs + one.worklogs, keys + one.keys
    return FetchResult(issues=issues, worklogs=worklogs, keys=keys)


async def _last_success() -> datetime | None:
    """When a sync last reached gold; None before the first one."""
    async with session_scope() as session:
        return (await AccountRepository(session).sync_state()).last_success_at


async def _record(error: str | None = None) -> None:
    """Stamp this run in `app.sync_state`. Best-effort: a stamp must not fail a sync."""
    try:
        async with session_scope() as session:
            await AccountRepository(session).record_sync(datetime.now(UTC), error)
    except Exception:
        log.warning("could not record the sync run", exc_info=True)


async def _queue_index() -> None:
    """Hand the embedding to the ingest worker; the scheduler never loads a model."""
    job = Job(kind=JobKind.INDEX_GOLD)
    async with session_scope() as session:
        await enqueue.stage(session, job)
    await enqueue.send(job)
