"""Knowledge base search over embeddings. Backend: Qdrant.

  client.py      connect to Qdrant, one shared client
  collections.py collection declarations: name, dimensions, metric, index settings
  indexer.py     generate embeddings from gold and upsert them into a collection
  search.py      queries: k-NN + metadata filtering

Why not `pgvector`: see `infra/__init__.py`.

Embeddings are generated from **gold**, not bronze — the same contract agents read. That way
search results and table queries can never contradict each other.
"""
