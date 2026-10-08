"""Nearest-neighbor queries, filtered by permission inside Qdrant."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from qdrant_client.models import Condition, FieldCondition, Filter, MatchAny, MatchValue

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.vectors import collections
from mycel.infra.vectors.client import client, embed

log = get_logger(__name__)

#: Max neighbors per query.
MAX_LIMIT = 20


@dataclass(frozen=True, slots=True)
class Hit:
    """One neighbour, as a caller outside this package sees it."""

    issue_key: str
    title: str
    status: str
    kind: str
    project: str
    assignee_name: str | None
    sprint_name: str | None
    score: float


async def search(
    query: str,
    projects: Sequence[str],
    limit: int,
    status_category: str | None = None,
) -> list[Hit]:
    """Nearest work items to `query` among readable `projects`; empty `projects` returns nothing."""
    if not projects or not query.strip():
        return []

    collection = collections.work_items(get_settings().embedding_model)
    qdrant = client()
    if not await qdrant.collection_exists(collection.name):
        # Nothing indexed yet: no answers, not an error.
        log.info("searched before indexing", extra={"collection": collection.name})
        return []

    # Typed as Filter's union: list is invariant, so list[FieldCondition] is rejected.
    conditions: list[Condition] = [
        FieldCondition(key="project", match=MatchAny(any=list(projects)))
    ]
    if status_category:
        conditions.append(
            FieldCondition(key="status_category", match=MatchValue(value=status_category))
        )

    vector = (await asyncio.to_thread(embed, [query]))[0]
    found = await qdrant.query_points(
        collection.name,
        query=vector,
        query_filter=Filter(must=conditions),
        limit=min(limit, MAX_LIMIT),
        with_payload=True,
    )
    return [_hit(point.payload or {}, point.score) for point in found.points]


def _hit(payload: dict[str, object], score: float) -> Hit:
    def text(key: str) -> str:
        value = payload.get(key)
        return str(value) if value is not None else ""

    def maybe(key: str) -> str | None:
        value = payload.get(key)
        return str(value) if value is not None else None

    return Hit(
        issue_key=text("issue_key"),
        title=text("title"),
        status=text("status"),
        kind=text("kind"),
        project=text("project"),
        assignee_name=maybe("assignee_name"),
        sprint_name=maybe("sprint_name"),
        score=score,
    )
