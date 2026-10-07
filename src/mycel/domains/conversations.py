"""Which conversations a person has.

The sidebar cannot show a history without knowing whose it is. A query, so it answers
inside the request — same reason as `domains/dashboard`.

The other list a UI needs, which projects have data, moved to `domains/dashboard` when
Jira became the source: it is a gold question now, and it belongs beside the other one.
"""

from dataclasses import dataclass

from mycel.infra.postgres.repositories.conversations import (
    ConversationRepository,
    ConversationRow,
    TurnRow,
)
from mycel.infra.postgres.session import session_scope

#: Most conversations one sidebar shows. Beyond this the list is an archive, and an archive
#: needs paging rather than a longer page.
HISTORY_LIMIT = 50


@dataclass(frozen=True)
class ConversationSummary:
    """One conversation, with what its latest run produced."""

    conversation: ConversationRow
    job_id: str | None
    status: str | None


async def list_conversations(user_id: int, limit: int = HISTORY_LIMIT) -> list[ConversationSummary]:
    """One person's sidebar, newest first.

    Each conversation carries its latest job id so clicking one can reopen the run without a
    second round-trip. A conversation whose run never finished has `None` for both — it was
    queued and the worker never got to it, which the page should show as such rather
    than hide.
    """
    async with session_scope() as session:
        repo = ConversationRepository(session)
        summaries = []
        for conversation in await repo.conversations_for(user_id, limit=limit):
            turns = await repo.turns_for_conversation(conversation.id)
            latest = turns[-1] if turns else None
            summaries.append(
                ConversationSummary(
                    conversation=conversation,
                    job_id=latest.job_id if latest else None,
                    status=latest.status if latest else None,
                )
            )
        return summaries


async def conversation_turns(user_id: int, conversation_id: int) -> list[TurnRow]:
    """Every run in one conversation, oldest first. Empty if it is not this person's.

    The page needs this because a conversation is now more than one turn: `?job=` names the
    run being watched, and the turns before it were never in this tab's memory. Empty
    rather than an exception for a conversation that is not theirs — same answer as a conversation
    that is not there, for the same reason as `forget_conversation`.
    """
    async with session_scope() as session:
        repo = ConversationRepository(session)
        conversation = await repo.conversation_by_id(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            return []
        return await repo.turns_for_conversation(conversation_id)


async def forget_conversation(user_id: int, conversation_id: int) -> bool:
    """Delete one conversation and its runs. False if it is not this person's, or not there.

    The two cases are one answer on purpose: telling a caller that a conversation exists but
    belongs to someone else is telling them something they did not have.
    """
    async with session_scope() as session:
        repo = ConversationRepository(session)
        return await repo.delete_conversation(conversation_id, user_id)


async def pin_conversation(user_id: int, conversation_id: int, pinned: bool) -> bool:
    """Pin or unpin one conversation. False if it is not this person's, or not there."""
    async with session_scope() as session:
        return await ConversationRepository(session).pin_conversation(
            conversation_id, user_id, pinned
        )
