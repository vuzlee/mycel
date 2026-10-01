"""An event the model has read out but nobody has agreed to yet.

**Why a draft exists at all.** The time in "three o'clock Friday for half an hour" is
something the model reads out of a sentence, and sentences are vague: which Friday, whose
afternoon, thirty minutes from when. Reading a calendar over the wrong window gives a
slightly odd answer; writing one to the wrong day puts a meeting nobody arranged on a real
person's phone. So `draft_event` writes nothing, reads the time back in words, and
`confirm_event` is what reaches Google.

**Redis with a TTL, not a table.** A draft that was never confirmed is a draft nobody wanted
— there is nothing to keep, nothing to report on, and nothing to migrate. Ten minutes is how
long "yes" stays a plausible answer to a question that was asked one turn ago.

The draft id travels through the conversation's own message history, which has carried tool
results since batch 032, so the model reads it back with no new machinery. It is spent on
confirmation, so an enthusiastic "yes, do it" twice over books one meeting.
"""

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime

from mycel.infra.redis.client import get_client

#: Long enough to read a sentence back and answer it, short enough that an abandoned draft
#: is gone before anyone could have forgotten agreeing to it.
DRAFT_TTL_S = 600


@dataclass(frozen=True)
class Draft:
    """A proposed event, as it waits to be agreed to.

    Carries `user_id` so confirmation cannot cross accounts: the id is a random string that
    travels through a prompt, and the only thing that should be able to spend it is the
    person whose calendar it was drafted against.
    """

    draft_id: str
    user_id: int
    summary: str
    starts_at: datetime
    ends_at: datetime


async def put(user_id: int, summary: str, starts_at: datetime, ends_at: datetime) -> Draft:
    """Keep a proposed event for ten minutes and return it, id and all."""
    draft = Draft(
        draft_id=secrets.token_urlsafe(8),
        user_id=user_id,
        summary=summary,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    client = await get_client()
    await client.set(_key(draft.draft_id), _dump(draft), ex=DRAFT_TTL_S)
    return draft


async def take(draft_id: str, user_id: int) -> Draft | None:
    """Spend a draft, or `None` if there is no such draft for this person.

    Deleted as it is read, so a second confirmation of the same draft books nothing. One
    answer for "expired", "never existed" and "belongs to somebody else", because telling
    them apart would mean saying whether a stranger's draft id is real.
    """
    client = await get_client()
    raw = await client.getdel(_key(draft_id))
    if raw is None:
        return None
    draft = _load(raw)
    if draft.user_id != user_id:
        return None
    return draft


def _key(draft_id: str) -> str:
    return f"mycel:draft:event:{draft_id}"


def _dump(draft: Draft) -> str:
    return json.dumps(
        {
            **asdict(draft),
            "starts_at": draft.starts_at.isoformat(),
            "ends_at": draft.ends_at.isoformat(),
        }
    )


def _load(raw: "bytes | str") -> Draft:
    """The client decodes responses, but its type says it may not — see `client.py`."""
    data = json.loads(raw)
    return Draft(
        draft_id=data["draft_id"],
        user_id=int(data["user_id"]),
        summary=data["summary"],
        starts_at=datetime.fromisoformat(data["starts_at"]),
        ends_at=datetime.fromisoformat(data["ends_at"]),
    )
