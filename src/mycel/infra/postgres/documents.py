"""Document status values. The tables themselves are `Document` and `Chunk` in `models.py`."""

UPLOADED = "uploaded"
PARSING = "parsing"
READY = "ready"
FAILED = "failed"
DELETING = "deleting"

#: While a user has a document in one of these, their knowledge base cannot be asked.
IN_FLIGHT = (UPLOADED, PARSING)
