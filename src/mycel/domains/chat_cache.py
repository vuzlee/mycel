"""Cached answers for a first question on work data: the same words, the same data, no model.

The key holds the asker, the sources, the model and its prompt, and the last successful
sync, so a new sync or a changed prompt simply misses. A turn that drafted or wrote
anything is never kept: its answer depends on more than the data.
"""

from typing import Any

from mycel.agents.specialists.orchestrator import Orchestrator
from mycel.core.chips import Chip
from mycel.infra.postgres.repositories.accounts import AccountRepository
from mycel.infra.postgres.session import session_scope
from mycel.infra.redis import answers

#: Tools whose call means the answer is about an action, not about the data.
_ACTING = frozenset({"draft_jira_write", "confirm_jira_write", "draft_event", "confirm_event"})


async def version(chips: frozenset[Chip] | None) -> str | None:
    """What the answer depends on besides the question; `None` when it must not be cached."""
    if chips is None or Chip.KNOWLEDGE in chips or chips - {Chip.JIRA}:
        # Knowledge has its own cache; mail, calendar and web change with no sync to key on.
        return None
    async with session_scope() as session:
        state = await AccountRepository(session).sync_state()
    synced = state.last_success_at.isoformat() if state.last_success_at else "never"
    return f"jira:{synced}"


def writer(model_ref: str) -> str:
    return answers.writer(Orchestrator.instructions, (model_ref, "work"))


def keepable(steps: list[dict[str, Any]]) -> bool:
    """False when the turn acted: a draft or a write is not an answer to replay."""
    return not any(str(s.get("payload", {}).get("tool", "")) in _ACTING for s in steps)
