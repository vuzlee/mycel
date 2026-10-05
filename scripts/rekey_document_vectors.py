"""Give every document passage in Qdrant an `owner_id`, after migration 0016.

    uv run python scripts/rekey_document_vectors.py

Before batch 066 points were keyed by `notebook_id`. This sets `owner_id` on every point
of every document from Postgres, and deletes points whose document no longer exists. No
passage is embedded again. Safe to run twice.
"""

import asyncio
import sys

from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue
from sqlalchemy import select

from mycel.infra.postgres.documents import Document
from mycel.infra.postgres.session import session_scope
from mycel.infra.vectors import documents as vectors
from mycel.infra.vectors.client import client


async def main() -> int:
    name = await vectors.ensure()
    async with session_scope() as session:
        rows = (await session.execute(select(Document.id, Document.owner_id))).all()
    owners = {document_id: owner_id for document_id, owner_id in rows}

    qdrant = client()
    seen: set[int] = set()
    offset = None
    while True:
        points, offset = await qdrant.scroll(name, limit=256, offset=offset, with_payload=True)
        seen.update(int((p.payload or {})["document_id"]) for p in points)
        if offset is None:
            break

    rekeyed = removed = 0
    for document_id in sorted(seen):
        by_document = Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=str(document_id)))]
        )
        owner = owners.get(document_id)
        if owner is None:
            await qdrant.delete(name, points_selector=FilterSelector(filter=by_document))
            removed += 1
            continue
        await qdrant.set_payload(name, {"owner_id": str(owner)}, points=by_document)
        await qdrant.delete_payload(name, ["notebook_id"], points=by_document)
        rekeyed += 1
    print(f"rekeyed {rekeyed} documents, removed points of {removed} gone documents")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
