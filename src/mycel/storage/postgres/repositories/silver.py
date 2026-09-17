"""Read raw, write silver: normalised schema, deduplicated, types coerced.

Deduplicate on the source's natural key (message id, thread id), not on a hash of the whole
record — a provider editing one field changes the hash and it becomes a new record.
"""
