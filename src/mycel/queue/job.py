"""A job's shape: kind of work, payload, idempotency key, retry count, trace context.

**The idempotency key is mandatory**, not optional. Acking after the work finishes gives
at-least-once: a worker dying mid-job means the broker redelivers it, and it had *already*
done part of the work. Without a key, one answer gets produced twice.

The key is derived from the work itself — kind plus the payload, hashed — not from a fresh
UUID. With a UUID, two identical requests produce two different keys, which is exactly what
we are trying to avoid. `job_id` is the per-attempt identity and *is* random: two callers
asking the same question get two job ids and one key, so both can poll for a result while
only one run happens.

Trace context lives in the message headers (see `context.py`), not in this model: headers
survive the trip through the dead-letter exchange, so even a failed job can have its trace
reopened to find out why.
"""

import hashlib
import json
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class JobKind(StrEnum):
    """What a worker is being asked to do.

    An enum rather than a free string: a typo in a routing key is a message that sits in a
    queue nobody consumes, which looks exactly like a slow worker.

    One member since batch 033, when the product became one chat box: `summary` had its own
    endpoint, and the capability is now reachable as a tool the orchestrator calls. Kept as
    an enum because the value is baked into `idempotency_key`, and a second kind of work is
    a member here rather than a string at every call site.
    """

    CHAT = "chat"


class Job(BaseModel):
    """One unit of work, as it travels through the broker.

    Serialised to JSON as the message body. Everything the worker needs to run the job is
    in here; everything needed to *trace* it is in the headers alongside.
    """

    kind: JobKind
    payload: dict[str, object] = Field(
        default_factory=dict,
        description=(
            "Arguments for this kind of work. For `chat`: `{'question', "
            "'conversation_id', 'history', 'user_id'}`."
        ),
    )
    job_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="This attempt's identity, used to poll for the result. Random.",
    )
    idempotency_key: str = Field(
        default="",
        description=(
            "Identity of the *work*, not of the request. Two callers asking the same "
            "question share this. Derived from kind + payload when left empty."
        ),
    )

    def model_post_init(self, _: object) -> None:
        """Fill the key from the work itself when the caller did not supply one.

        Done here rather than in a `default_factory`, which cannot see the other fields.
        """
        if not self.idempotency_key:
            # `sort_keys` because two dicts equal in Python but built in a different order
            # must not hash differently — that would silently defeat the whole mechanism.
            body = json.dumps(
                {"kind": str(self.kind), "payload": self.payload},
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            digest = hashlib.sha256(body.encode()).hexdigest()[:32]
            object.__setattr__(self, "idempotency_key", f"{self.kind}:{digest}")
