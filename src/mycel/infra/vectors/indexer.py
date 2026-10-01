"""Gold into Qdrant: embed what changed, upsert it, leave the rest alone.

Background work, never inside a request — embedding fifty items takes seconds, and a
question waiting on it is a question that times out.

**A stable id, so re-running changes nothing.** The id is a UUID derived from
`(source, issue_key)`, which is gold's own natural key. Qdrant upserts on id, so a second
pass over the same item overwrites its point rather than adding a second one. That is the
same idempotence `etl/` relies on, and it is what makes "run it again" a safe answer to
every doubt.

**Only what moved gets embedded.** Each point carries the `updated_at` it was built from.
A pass asks Qdrant what it already knows, compares, and embeds only the rows gold has
touched since — so a sync that changed three issues costs three embeddings rather than
fifty-two. The scheduler ticks every fifteen minutes; without this, that is ninety-six full
passes a day for nothing.

**No deletes, because gold has none.** `GoldRepository` only ever upserts — an issue
removed in Jira keeps its gold row — so there is no path by which a point outlives the row
it came from. If gold ever learns to delete, this file has to learn it on the same day, or
search starts returning rows that no longer exist.
"""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from qdrant_client.models import PointStruct
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.postgres.repositories.gold import GoldRepository, WorkItemRow
from mycel.infra.vectors import collections
from mycel.infra.vectors.client import client, embed

log = get_logger(__name__)

#: The namespace the point ids are drawn from. Any fixed UUID does; this one is arbitrary
#: and must never change, because changing it re-ids every point and doubles the collection.
_NAMESPACE = uuid.UUID("6f3c1f2e-8f4a-4d6b-9a7e-2c5b1d0e8a44")

#: How many items are embedded in one call. Large enough that the model's fixed cost is
#: amortised, small enough that a failure loses a batch rather than a pass.
BATCH = 64


@dataclass(frozen=True, slots=True)
class IndexResult:
    """What one pass did, in the terms the caller reports."""

    seen: int
    embedded: int
    skipped: int


def point_id(source: str, issue_key: str) -> str:
    """The id for one work item. Same inputs, same id, forever."""
    return str(uuid.uuid5(_NAMESPACE, f"{source}:{issue_key}"))


def document(item: WorkItemRow) -> str:
    """The text that gets embedded.

    Title first and alone on its line, because it carries most of the meaning and a model
    weights early tokens more. The rest is labelled so the embedding of "Done" as a status
    does not collide with "done" in a title.

    Deliberately not included: ids, timestamps, and effort in seconds. A number embeds as
    noise — nobody searches for "28800 seconds" — and the way to ask about those is SQL,
    which `run_sql` already does better than any similarity search would.
    """
    parts = [item.title, f"status: {item.status} ({item.status_category})", f"type: {item.kind}"]
    if item.assignee_name:
        parts.append(f"assignee: {item.assignee_name}")
    if item.sprint_name:
        parts.append(f"sprint: {item.sprint_name}")
    if item.labels:
        parts.append(f"labels: {', '.join(item.labels)}")
    return "\n".join(parts)


def payload(item: WorkItemRow) -> dict[str, object]:
    """What travels with the vector.

    Enough to render a result without going back to Postgres, plus the fields a filter
    needs. `updated_at` is stored as a unix timestamp rather than a string so the next pass
    can compare it without parsing, and `project` is here because it is what a permission
    filter matches on — see `search.py`.
    """
    return {
        "source": item.source,
        "project": item.project,
        "issue_key": item.issue_key,
        "title": item.title,
        "status": item.status,
        "status_category": item.status_category,
        "kind": item.kind,
        "assignee_name": item.assignee_name,
        "sprint_name": item.sprint_name,
        "updated_at": item.updated_at.timestamp(),
    }


async def ensure_collection() -> collections.Collection:
    """The collection, created if this is the first run. Safe to call every time."""
    collection = collections.work_items(get_settings().embedding_model)
    qdrant = client()
    if not await qdrant.collection_exists(collection.name):
        await qdrant.create_collection(collection.name, vectors_config=collection.params)
        log.info(
            "created collection",
            extra={"collection": collection.name, "dimensions": collection.dimensions},
        )
    return collection


async def _known(collection: str, ids: Sequence[str]) -> dict[str, float]:
    """The `updated_at` Qdrant already holds for each of these ids.

    One retrieve for the whole batch rather than one per item: the ids are known up front,
    so there is no reason to pay a round trip each.
    """
    if not ids:
        return {}
    found = await client().retrieve(
        collection, ids=list(ids), with_payload=True, with_vectors=False
    )
    return {str(p.id): float((p.payload or {}).get("updated_at", 0.0)) for p in found}


async def index_items(items: Sequence[WorkItemRow]) -> IndexResult:
    """Embed and upsert the ones that moved. Returns what it did.

    The comparison is on `updated_at` alone. Gold writes that field on every change, so an
    item whose timestamp matches what Qdrant holds cannot have changed — and an item whose
    text happens to be identical after a change is embedded again for nothing, which costs
    one local embedding and keeps the rule simple enough to trust.
    """
    if not items:
        return IndexResult(seen=0, embedded=0, skipped=0)

    collection = await ensure_collection()
    embedded = skipped = 0

    for start in range(0, len(items), BATCH):
        batch = items[start : start + BATCH]
        ids = [point_id(item.source, item.issue_key) for item in batch]
        known = await _known(collection.name, ids)

        stale = [
            (pid, item)
            for pid, item in zip(ids, batch, strict=True)
            if known.get(pid) != item.updated_at.timestamp()
        ]
        skipped += len(batch) - len(stale)
        if not stale:
            continue

        documents = [document(item) for _, item in stale]
        vectors = await asyncio.to_thread(embed, documents)
        await client().upsert(
            collection.name,
            points=[
                PointStruct(id=pid, vector=vector, payload=payload(item))
                for (pid, item), vector in zip(stale, vectors, strict=True)
            ],
        )
        embedded += len(stale)

    log.info(
        "indexed gold",
        extra={"seen": len(items), "embedded": embedded, "skipped": skipped},
    )
    return IndexResult(seen=len(items), embedded=embedded, skipped=skipped)


async def index_project(
    session: AsyncSession, project: str, since: datetime | None = None
) -> IndexResult:
    """One project's work items, from `since` onwards. None means everything.

    `since` is an optimisation, not the correctness mechanism: passing None still embeds
    only what changed, because `index_items` compares every item against what Qdrant holds.
    It is there so a routine pass need not load fifty-two rows to discover it has nothing
    to do.
    """
    repo = GoldRepository(session)
    window = since or datetime(1970, 1, 1, tzinfo=UTC)
    return await index_items(await repo.items_between(project, since=window))
