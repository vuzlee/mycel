"""Gold into Qdrant: embed what changed, upsert it under stable ids, leave the rest."""

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

#: Fixed namespace for point ids; changing it re-ids every point.
_NAMESPACE = uuid.UUID("6f3c1f2e-8f4a-4d6b-9a7e-2c5b1d0e8a44")

#: Items per embedding call.
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
    """The text that gets embedded: title first, then labelled fields."""
    parts = [item.title, f"status: {item.status} ({item.status_category})", f"type: {item.kind}"]
    if item.assignee_name:
        parts.append(f"assignee: {item.assignee_name}")
    if item.sprint_name:
        parts.append(f"sprint: {item.sprint_name}")
    if item.labels:
        parts.append(f"labels: {', '.join(item.labels)}")
    return "\n".join(parts)


def payload(item: WorkItemRow) -> dict[str, object]:
    """What travels with the vector; `updated_at` as a unix timestamp for comparison."""
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
    """The collection, created on first run. Safe to call every time."""
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
    """The `updated_at` Qdrant holds for each id, in one retrieve."""
    if not ids:
        return {}
    found = await client().retrieve(
        collection, ids=list(ids), with_payload=True, with_vectors=False
    )
    return {str(p.id): float((p.payload or {}).get("updated_at", 0.0)) for p in found}


async def index_items(items: Sequence[WorkItemRow]) -> IndexResult:
    """Embed and upsert items whose `updated_at` differs from Qdrant's."""
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


async def index_project(session: AsyncSession, project: str) -> IndexResult:
    """Embed a project's items; `index_items` skips what Qdrant already holds unchanged."""
    items = await GoldRepository(session).items_between(
        project, since=datetime(1970, 1, 1, tzinfo=UTC)
    )
    return await index_items(items)
