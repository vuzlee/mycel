"""Generate embeddings from gold and upsert them into Qdrant. Runs in the background, never
inside a request.

Upserts use a stable id derived from the gold record's key, so re-running produces no
duplicates — the same idempotent spirit as `etl/`.

Generating embeddings is high-volume batch work: exactly the kind of job to push to a local
model (`llm/router.py` picks tier LOCAL) instead of burning cloud quota.
"""
