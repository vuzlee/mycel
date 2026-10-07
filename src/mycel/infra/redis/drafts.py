"""Something the model has read out but nobody has agreed to yet.

**Why a draft exists at all.** The time in "three o'clock Friday for half an hour" is
something the model reads out of a sentence, and sentences are vague: which Friday, whose
afternoon, thirty minutes from when. Reading a calendar over the wrong window gives a
slightly odd answer; writing one to the wrong day puts a meeting nobody arranged on a real
person's phone. So `draft_event` writes nothing, reads the time back in words, and
`confirm_event` is what reaches Google.

**Redis with a TTL, not a table.** A draft that was never confirmed is a draft nobody wanted
— there is nothing to keep, nothing to report on, and nothing to migrate. Ten minutes is how
long "yes" stays a plausible answer to a question that was asked one turn ago.

The draft id travels through the conversation's own message history, which carries tool
results, so the model reads it back with no new machinery. It is spent on
confirmation, so an enthusiastic "yes, do it" twice over books one meeting.

**Two kinds, and the second is a Jira write.** The same argument holds: "assign it to Nam" is a name
the model turns into an account id, and a wrong one
is almost always the *wrong person* rather than a malformed id — two people share a name, or
one has left. So the write is read back by full name and nothing reaches Jira until someone
says yes. Each kind has its own key prefix and its own `put`/`take` pair, so a draft of one
kind can never be spent as the other.

A Jira draft can also come *back*: a write that is certain not to have landed restores it
under the same id, so a second yes is a retry rather than a whole new round. See
`restore_jira`.
"""

import secrets
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from mycel.infra.redis.client import get_client

#: Long enough to read a sentence back and answer it, short enough that an abandoned draft
#: is gone before anyone could have forgotten agreeing to it.
DRAFT_TTL_S = 600


class Draft(BaseModel):
    """A proposed event, as it waits to be agreed to.

    Carries `user_id` so confirmation cannot cross accounts: the id is a random string that
    travels through a prompt, and the only thing that should be able to spend it is the
    person whose calendar it was drafted against.
    """

    model_config = ConfigDict(frozen=True)

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
    await client.set(_key(draft.draft_id), draft.model_dump_json(), ex=DRAFT_TTL_S)
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
    draft = Draft.model_validate_json(raw)
    if draft.user_id != user_id:
        return None
    return draft


def _key(draft_id: str) -> str:
    return f"mycel:draft:event:{draft_id}"


class JiraDraft(BaseModel):
    """A proposed write to Jira, as it waits to be agreed to.

    One shape for all four writes rather than four dataclasses: what differs between them
    is which fields are filled, and a confirm that has to branch on a type anyway gains
    nothing from four. `kind` says which write this is; `spelled` is the sentence the person
    reads, built where the draft is made because that is where the full names are known.

    Carries `user_id` for the reason the event draft does — the id travels through a prompt,
    and the only person who may spend it is the one it was drafted for.
    """

    model_config = ConfigDict(frozen=True)

    draft_id: str
    user_id: int
    #: "comment" | "move" | "issue" | "project"
    kind: str
    #: What the person is shown and asked to confirm. Full names, never ids.
    spelled: str
    #: The call's arguments, already resolved — account ids looked up, keys upper-cased.
    #: Resolved at draft time, so what is confirmed is exactly what is written.
    payload: dict[str, Any]


async def put_jira(user_id: int, kind: str, spelled: str, payload: dict[str, Any]) -> JiraDraft:
    """Keep a proposed Jira write for ten minutes and return it, id and all."""
    draft = JiraDraft(
        draft_id=secrets.token_urlsafe(8),
        user_id=user_id,
        kind=kind,
        spelled=spelled,
        payload=payload,
    )
    client = await get_client()
    await client.set(_jira_key(draft.draft_id), draft.model_dump_json(), ex=DRAFT_TTL_S)
    return draft


async def take_jira(draft_id: str, user_id: int) -> JiraDraft | None:
    """Spend a Jira draft, or `None` if there is no such draft for this person.

    Deleted as it is read, so a second confirmation writes nothing. One answer for
    "expired", "never existed" and "belongs to somebody else", because telling them apart
    would mean saying whether a stranger's draft id is real.
    """
    client = await get_client()
    raw = await client.getdel(_jira_key(draft_id))
    if raw is None:
        return None
    draft = JiraDraft.model_validate_json(raw)
    return draft if draft.user_id == user_id else None


async def restore_jira(draft: JiraDraft) -> None:
    """Put a spent draft back, under its own id, for a write that cannot have landed.

    `take_jira` spends the draft before the write is attempted, which is right for a write
    that succeeds and wrong for one that was refused: the person has already read the
    change back and already agreed to it, and making them do the whole round again for a
    refused connection is making them pay for the provider's bad minute.

    **Only ever called on `sources.NotWritten`.** Restoring after a timeout would offer a
    retry for a request that may well have landed, and a second yes would post the comment
    twice. The id is kept so the sentence the tool returns can name it and the model can
    confirm again rather than drafting afresh.

    The TTL starts over. Ten minutes from the failure is the same promise the draft made in
    the first place — long enough to answer, short enough that an abandoned one is gone.
    """
    client = await get_client()
    await client.set(_jira_key(draft.draft_id), draft.model_dump_json(), ex=DRAFT_TTL_S)


def _jira_key(draft_id: str) -> str:
    return f"mycel:draft:jira:{draft_id}"
