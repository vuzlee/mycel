"""Give every document vector a `user_id` payload, copied from its `owner_id`.

    uv run python scripts/data/qdrant_owner_to_user.py

Runs with migration 0020. Adds the field and its index and removes nothing, so it is safe
to run twice and the old code still reads `owner_id`. A point that already has `user_id`
is left as it is.
"""

import asyncio
import sys

from qdrant_client.models import (
    Filter,
    IsEmptyCondition,
    KeywordIndexParams,
    KeywordIndexType,
    PayloadField,
)

from mycel.infra.vectors import documents
from mycel.infra.vectors.client import client

PAGE = 256


async def main() -> int:
    qdrant = client()
    name = documents.collection_name()
    if not await qdrant.collection_exists(name):
        print(f"{name}: no collection, nothing to do")
        return 0
    await qdrant.create_payload_index(
        name,
        "user_id",
        field_schema=KeywordIndexParams(type=KeywordIndexType.KEYWORD, is_tenant=True),
    )
    missing = Filter(must=[IsEmptyCondition(is_empty=PayloadField(key="user_id"))])
    written = 0
    offset = None
    while True:
        points, offset = await qdrant.scroll(
            name, scroll_filter=missing, limit=PAGE, offset=offset, with_payload=["owner_id"]
        )
        for point in points:
            owner = (point.payload or {}).get("owner_id")
            if owner is None:
                continue
            await qdrant.set_payload(name, {"user_id": owner}, points=[point.id])
            written += 1
        if offset is None:
            break
    left = await qdrant.count(name, count_filter=missing, exact=True)
    total = await qdrant.count(name, exact=True)
    print(f"{name}: wrote user_id on {written}; {left.count} of {total.count} still without it")
    return 0 if left.count == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
