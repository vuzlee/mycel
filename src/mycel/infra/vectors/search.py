"""Queries: nearest neighbours, filtered inside Qdrant.

**The filter runs in Qdrant, not after the results come back.** Fetching the ten nearest
and then dropping the ones the asker may not see can leave two — and two is a wrong answer,
not a short one, because the eight that would have filled the gap were never asked for.
Qdrant applies the filter during the search, so ten asked for is ten allowed returned when
ten allowed exist.

The allowed projects come from `services/permission.py`, the same `app.membership` rule
`run_sql` is bounded by. One rule, read in two places — not two rules that must agree.

Agents reach this through `agents/tools/rag_search.py`, never by importing it.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from qdrant_client.models import Condition, FieldCondition, Filter, MatchAny, MatchValue

from mycel.core.config import get_settings
from mycel.core.logging import get_logger
from mycel.infra.vectors import collections
from mycel.infra.vectors.client import client, embed

log = get_logger(__name__)

#: The most neighbours one query may ask for. Beyond this a search stops being a search and
#: becomes a listing, which SQL does better and without a model in the loop.
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
    """The nearest work items to `query`, from projects the asker may read.

    An empty `projects` returns nothing rather than everything. That is the whole of the
    permission model here, and it is written as an early return rather than as an empty
    filter — an empty `MatchAny` matches nothing in Qdrant today, but relying on that is
    relying on a detail of someone else's query planner.
    """
    if not projects or not query.strip():
        return []

    collection = collections.work_items(get_settings().embedding_model)
    qdrant = client()
    if not await qdrant.collection_exists(collection.name):
        # Nothing indexed yet. Not an error: a deployment that has never run the indexer
        # has no answers, and saying so beats a stack trace in the middle of a run.
        log.info("searched before indexing", extra={"collection": collection.name})
        return []

    # Typed as the union Filter takes, not as list[FieldCondition]: a list is invariant,
    # so the narrower type is rejected at the call below.
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
