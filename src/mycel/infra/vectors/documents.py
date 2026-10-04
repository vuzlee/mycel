"""Notebook passages in Qdrant: write, hide, delete, search. Filters run inside Qdrant.

The payload carries ids and the `enabled` flag, never permissions: who may read a
notebook is decided in Postgres at question time.
"""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from qdrant_client.models import (
    FieldCondition,
    Filter,
    FilterSelector,
    KeywordIndexParams,
    KeywordIndexType,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
)

from mycel.core.config import get_settings
from mycel.infra.vectors import collections
from mycel.infra.vectors.client import client, embed

_NAMESPACE = uuid.UUID("0b8f3c2a-5d61-4e2f-9a7c-61e4d2b8f013")
BATCH = 32

_ready = False


@dataclass(frozen=True, slots=True)
class Hit:
    chunk_id: int
    document_id: int
    score: float


def point_id(document_id: int, ord: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{document_id}:{ord}"))


def _collection() -> collections.Collection:
    return collections.documents(get_settings().document_embedding_model)


async def ensure() -> str:
    """Create the collection and its payload indexes once per process."""
    global _ready
    name = _collection().name
    if _ready:
        return name
    qdrant = client()
    if not await qdrant.collection_exists(name):
        await qdrant.create_collection(name, vectors_config=_collection().params)
        await qdrant.create_payload_index(
            name,
            "notebook_id",
            field_schema=KeywordIndexParams(type=KeywordIndexType.KEYWORD, is_tenant=True),
        )
        await qdrant.create_payload_index(name, "document_id", PayloadSchemaType.KEYWORD)
        await qdrant.create_payload_index(name, "enabled", PayloadSchemaType.BOOL)
    _ready = True
    return name


async def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    model = get_settings().document_embedding_model
    return await asyncio.to_thread(embed, list(texts), model)


async def write(
    notebook_id: int,
    document_id: int,
    enabled: bool,
    chunk_ids: Sequence[int],
    texts: Sequence[str],
) -> None:
    """Embed and upsert one document's passages, `BATCH` at a time."""
    name = await ensure()
    for start in range(0, len(texts), BATCH):
        part = texts[start : start + BATCH]
        vectors = await embed_texts(part)
        points = [
            PointStruct(
                id=point_id(document_id, start + i),
                vector=vector,
                payload={
                    "notebook_id": str(notebook_id),
                    "document_id": str(document_id),
                    "chunk_id": chunk_ids[start + i],
                    "enabled": enabled,
                },
            )
            for i, vector in enumerate(vectors)
        ]
        await client().upsert(name, points=points)


async def set_enabled(document_id: int, enabled: bool) -> None:
    name = await ensure()
    await client().set_payload(name, {"enabled": enabled}, points=_by_document(document_id))


async def delete(document_id: int) -> None:
    name = await ensure()
    await client().delete(name, points_selector=FilterSelector(filter=_by_document(document_id)))


async def count(document_id: int) -> int:
    name = await ensure()
    result = await client().count(name, count_filter=_by_document(document_id), exact=True)
    return result.count


async def search(notebook_id: int, query: str, limit: int) -> list[Hit]:
    """The nearest enabled passages in one notebook."""
    name = await ensure()
    vector = (await embed_texts([query]))[0]
    found = await client().query_points(
        name,
        query=vector,
        query_filter=Filter(
            must=[
                FieldCondition(key="notebook_id", match=MatchValue(value=str(notebook_id))),
                FieldCondition(key="enabled", match=MatchValue(value=True)),
            ]
        ),
        limit=limit,
        with_payload=True,
    )
    return [
        Hit(int((p.payload or {})["chunk_id"]), int((p.payload or {})["document_id"]), p.score)
        for p in found.points
    ]


def _by_document(document_id: int) -> Filter:
    return Filter(
        must=[FieldCondition(key="document_id", match=MatchValue(value=str(document_id)))]
    )
