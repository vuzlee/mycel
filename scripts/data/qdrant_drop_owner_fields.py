"""Remove the old `owner_id` and `notebook_id` payload fields and their indexes.

    uv run python scripts/data/qdrant_drop_owner_fields.py

Follows qdrant_owner_to_user.py. Refuses to run while any point still lacks `user_id`.
"""

import asyncio
import sys

from qdrant_client.models import Filter, IsEmptyCondition, PayloadField

from mycel.infra.vectors import documents
from mycel.infra.vectors.client import client

OLD = ["owner_id", "notebook_id"]


def has(key: str) -> Filter:
    return Filter(must_not=[IsEmptyCondition(is_empty=PayloadField(key=key))])


async def main() -> int:
    qdrant = client()
    name = documents.collection_name()
    if not await qdrant.collection_exists(name):
        print(f"{name}: no collection, nothing to do")
        return 0
    missing = Filter(must=[IsEmptyCondition(is_empty=PayloadField(key="user_id"))])
    left = await qdrant.count(name, count_filter=missing, exact=True)
    if left.count:
        print(f"{name}: {left.count} points lack user_id; run qdrant_owner_to_user.py first")
        return 1
    await qdrant.delete_payload(name, keys=OLD, points=Filter())
    schema = (await qdrant.get_collection(name)).payload_schema or {}
    for key in OLD:
        if key in schema:
            await qdrant.delete_payload_index(name, key)
    remaining = {
        key: (await qdrant.count(name, count_filter=has(key), exact=True)).count for key in OLD
    }
    print(f"{name}: points still carrying old fields: {remaining}")
    return 0 if not any(remaining.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
