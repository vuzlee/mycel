"""A job as it travels through the broker. Trace context rides in the headers."""

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class JobKind(StrEnum):
    CHAT = "chat"
    INGEST = "ingest"
    DELETE_DOCUMENT = "delete_document"
    INDEX_GOLD = "index_gold"
    SYNC_JIRA = "sync_jira"
    CHECK_KEYS = "check_keys"


#: Kinds that run on the ingest worker, which holds the embedding models and the RAM.
INGEST_KINDS = frozenset({JobKind.INGEST, JobKind.DELETE_DOCUMENT, JobKind.INDEX_GOLD})


class Job(BaseModel):
    kind: JobKind
    payload: dict[str, object] = Field(default_factory=dict)
    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
