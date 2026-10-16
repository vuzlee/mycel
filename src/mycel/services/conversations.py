"""Which conversations a person has."""

from dataclasses import dataclass

from mycel.infra.postgres.repositories.conversations import (
    ConversationRepository,
    ConversationRow,
    TurnRow,
)
from mycel.infra.postgres.session import session_scope

#: Most conversations one sidebar shows.
HISTORY_LIMIT = 50


@dataclass(frozen=True)
class ConversationSummary:
    """One conversation, with what its latest run produced."""

    conversation: ConversationRow
    job_id: str | None
    status: str | None


async def list_conversations(user_id: int, limit: int = HISTORY_LIMIT) -> list[ConversationSummary]:
    """One person's sidebar, newest first."""
    async with session_scope() as session:
        repo = ConversationRepository(session)
        conversations = await repo.conversations_for(user_id, limit=limit)
        latest = await repo.latest_turns([c.id for c in conversations])
    return [
        ConversationSummary(
            conversation=c,
            job_id=latest[c.id][0] if c.id in latest else None,
            status=latest[c.id][1] if c.id in latest else None,
        )
        for c in conversations
    ]


async def conversation_turns(user_id: int, conversation_id: int) -> list[TurnRow]:
    """Every run in one conversation, oldest first. Empty if it is not this person's."""
    async with session_scope() as session:
        repo = ConversationRepository(session)
        conversation = await repo.conversation_by_id(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            return []
        return await repo.turns_for_conversation(conversation_id)


async def forget_conversation(user_id: int, conversation_id: int) -> bool:
    """Delete one conversation and its runs. False if it is not this person's, or not there."""
    async with session_scope() as session:
        repo = ConversationRepository(session)
        return await repo.delete_conversation(conversation_id, user_id)


async def pin_conversation(user_id: int, conversation_id: int, pinned: bool) -> bool:
    """Pin or unpin one conversation. False if it is not this person's, or not there."""
    async with session_scope() as session:
        return await ConversationRepository(session).pin_conversation(
            conversation_id, user_id, pinned
        )


async def edit_conversation(
    user_id: int, conversation_id: int, *, title: str | None, archived: bool | None
) -> bool:
    """Rename or archive one conversation. False if it is not this person's, or not there."""
    async with session_scope() as session:
        return await ConversationRepository(session).edit_conversation(
            conversation_id, user_id, title=title, archived=archived
        )
