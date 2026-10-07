"""Conversations and the turns inside them, in `app`."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import (
    Conversation,
    Turn,
)
from mycel.infra.postgres.repositories._result import rowcount


@dataclass(frozen=True)
class ConversationRow:
    """One conversation in the sidebar."""

    id: int
    user_id: int
    kind: str
    title: str
    created_at: datetime
    pinned_at: datetime | None = None


@dataclass(frozen=True)
class TurnRow:
    """One question and what came back, as kept."""

    id: int
    conversation_id: int
    job_id: str
    question: str
    status: str
    answer: str | None
    error: str | None
    spent_usd: Decimal | None
    #: The tool calls this turn made, as the stream sent them. `None` for a turn recorded
    #: without steps, and for one that failed.
    steps: list[Any] | None
    created_at: datetime


class ConversationRepository:
    """Reads and writes these tables on a session someone else owns, so callers can share
    one transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_conversation(self, user_id: int, kind: str, title: str) -> ConversationRow:
        """Start a conversation."""
        row = Conversation(user_id=user_id, kind=kind, title=title)
        self._session.add(row)
        await self._session.flush()
        return _conversation(row)

    async def conversations_for(
        self, user_id: int, kind: str | None = None, limit: int = 50
    ) -> list[ConversationRow]:
        """One person's sidebar, most recently spoken to first.

        Ordered by the newest turn, not by when the conversation was opened. A conversation you went
        back to this morning is the one you are working in, and ordering by `created_at`
        buries it under every conversation opened since — which is the opposite of what a
        history is for.

        `COALESCE` because a conversation with no turns still has to sort: it was opened and the
        worker never wrote a row, and its own `created_at` is the only time it has.

        `updated_at` rather than `created_at`: a turn row is written when the question is
        queued and written again when the run ends, and it is the ending people watch for.
        Ordering on the first write leaves a conversation sitting where it was while its answer
        lands somewhere down the list.
        """
        spoke = (
            select(Turn.conversation_id, func.max(Turn.updated_at).label("at"))
            .group_by(Turn.conversation_id)
            .subquery()
        )
        query = (
            select(Conversation)
            .outerjoin(spoke, spoke.c.conversation_id == Conversation.id)
            .where(Conversation.user_id == user_id)
        )
        if kind is not None:
            query = query.where(Conversation.kind == kind)
        # Pinned first, newest pin on top; pins never fall off the end of the page.
        rows = await self._session.scalars(
            query.order_by(
                Conversation.pinned_at.desc().nulls_last(),
                func.coalesce(spoke.c.at, Conversation.created_at).desc(),
            ).limit(limit)
        )
        return [_conversation(row) for row in rows]

    async def conversation_by_id(self, conversation_id: int) -> ConversationRow | None:
        """One conversation, whoever owns it. The caller checks that it is theirs."""
        row = await self._session.scalar(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        return _conversation(row) if row else None

    async def pin_conversation(self, conversation_id: int, user_id: int, pinned: bool) -> bool:
        """Pin or unpin a conversation. Scoped by `user_id` in the WHERE, like the delete."""
        result = await self._session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .values(pinned_at=func.now() if pinned else None)
        )
        return bool(rowcount(result))

    async def delete_conversation(self, conversation_id: int, user_id: int) -> bool:
        """Forget a conversation, and every run under it.

        `user_id` is in the WHERE rather than checked by the caller: a delete that scopes
        itself cannot be made to delete someone else's row by a caller that forgot. The
        turns go with it through `ON DELETE CASCADE`.
        """
        result = await self._session.execute(
            delete(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
        return bool(rowcount(result))

    async def upsert_turn(
        self,
        conversation_id: int,
        job_id: str,
        question: str,
        status: str,
        answer: str | None = None,
        error: str | None = None,
        spent_usd: Decimal | None = None,
        steps: list[Any] | None = None,
    ) -> None:
        """Write a turn's state, replacing whatever that job id last said.

        Upsert because a job is written twice — once as `queued` when it is enqueued and
        again when it finishes — and a third time if the broker redelivers it.

        `updated_at` is set by hand. The model declares `onupdate`, but that is an ORM hook
        and this is a Core `INSERT ... ON CONFLICT`, which never runs it — the column would
        keep the moment the job was queued, and the sidebar orders on it.
        """
        stmt = insert(Turn).values(
            conversation_id=conversation_id,
            job_id=job_id,
            question=question,
            status=status,
            answer=answer,
            error=error,
            spent_usd=spent_usd,
            steps=steps,
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_turn_job_id",
                set_={
                    "status": stmt.excluded.status,
                    "answer": stmt.excluded.answer,
                    "error": stmt.excluded.error,
                    "spent_usd": stmt.excluded.spent_usd,
                    # Coalesced, not overwritten: a redelivery that ends in failure must
                    # not wipe the steps a successful earlier attempt already wrote.
                    "steps": func.coalesce(stmt.excluded.steps, Turn.steps),
                    "updated_at": func.now(),
                },
            )
        )

    async def turn_by_job_id(self, job_id: str) -> TurnRow | None:
        """What a job produced, however long ago — this is the record Redis is not."""
        row = await self._session.scalar(select(Turn).where(Turn.job_id == job_id))
        return _turn(row) if row else None

    async def turns_for_conversation(self, conversation_id: int) -> list[TurnRow]:
        """Every turn in a conversation, oldest first."""
        rows = await self._session.scalars(
            select(Turn).where(Turn.conversation_id == conversation_id).order_by(Turn.created_at)
        )
        return [_turn(row) for row in rows]


def _conversation(row: Conversation) -> ConversationRow:
    return ConversationRow(
        id=row.id,
        user_id=row.user_id,
        kind=row.kind,
        title=row.title,
        created_at=row.created_at,
        pinned_at=row.pinned_at,
    )


def _turn(row: Turn) -> TurnRow:
    return TurnRow(
        id=row.id,
        conversation_id=row.conversation_id,
        job_id=row.job_id,
        question=row.question,
        status=row.status,
        answer=row.answer,
        error=row.error,
        spent_usd=row.spent_usd,
        steps=row.steps,
        created_at=row.created_at,
    )
