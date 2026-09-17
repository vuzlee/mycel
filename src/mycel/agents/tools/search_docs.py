"""Semantic search over the knowledge base. Calls `storage/vectors/search.py`.

Returns passages together with their **source** (which gold record, original link) — not
content alone. Without a source `reviewer.py` has no way to verify anything, and the
report becomes a set of assertions that cannot be cited.

View permissions are pushed down into Qdrant's filter, not applied after results come back.
"""
