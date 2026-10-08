"""Proposed calendar and Jira writes, held with a TTL until the user confirms."""

import secrets
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from mycel.infra.redis.client import get_client

#: Long enough to confirm, short enough that an abandoned draft is gone.
DRAFT_TTL_S = 600


class Draft(BaseModel):
    """A proposed event; `user_id` stops a draft being confirmed from another account."""

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
    """Spend a draft, or `None` if this person has no such draft. Deleted on read."""
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
    """A proposed Jira write; one shape for all four kinds."""

    model_config = ConfigDict(frozen=True)

    draft_id: str
    user_id: int
    #: "comment" | "move" | "issue" | "project"
    kind: str
    #: What the person is shown and asked to confirm. Full names, never ids.
    spelled: str
    #: Resolved arguments (ids looked up), so what is confirmed is exactly what is written.
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
    """Spend a Jira draft, or `None` if this person has no such draft. Deleted on read."""
    client = await get_client()
    raw = await client.getdel(_jira_key(draft_id))
    if raw is None:
        return None
    draft = JiraDraft.model_validate_json(raw)
    return draft if draft.user_id == user_id else None


async def restore_jira(draft: JiraDraft) -> None:
    """Put a spent draft back under its own id, for a write that cannot have landed."""
    client = await get_client()
    await client.set(_jira_key(draft.draft_id), draft.model_dump_json(), ex=DRAFT_TTL_S)


def _jira_key(draft_id: str) -> str:
    return f"mycel:draft:jira:{draft_id}"
