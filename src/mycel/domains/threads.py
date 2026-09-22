"""Which threads a person has.

The sidebar cannot show a history without knowing whose it is. A query, so it answers
inside the request — same reason as `domains/dashboard`.

The other list a UI needs, which projects have data, moved to `domains/dashboard` when
Jira became the source: it is a gold question now, and it belongs beside the other one.
"""

from dataclasses import dataclass

from mycel.infra.postgres.repositories.app import AppRepository, ConversationRow, ReportRow
from mycel.infra.postgres.session import session_scope

#: Most threads one sidebar shows. Beyond this the list is an archive, and an archive
#: needs paging rather than a longer page.
HISTORY_LIMIT = 50


@dataclass(frozen=True)
class Thread:
    """One conversation, with what its latest run produced."""

    conversation: ConversationRow
    job_id: str | None
    status: str | None


async def list_threads(user_id: int, limit: int = HISTORY_LIMIT) -> list[Thread]:
    """One person's sidebar, newest first.

    Each thread carries its latest job id so clicking one can reopen the run without a
    second round-trip. A thread whose run never finished has `None` for both — it was
    queued and the worker never got to it, which the page should show as such rather
    than hide.
    """
    async with session_scope() as session:
        repo = AppRepository(session)
        threads = []
        for conversation in await repo.conversations_for(user_id, limit=limit):
            reports = await repo.reports_for_conversation(conversation.id)
            latest = reports[-1] if reports else None
            threads.append(
                Thread(
                    conversation=conversation,
                    job_id=latest.job_id if latest else None,
                    status=latest.status if latest else None,
                )
            )
        return threads


async def thread_turns(user_id: int, conversation_id: int) -> list[ReportRow]:
    """Every run in one thread, oldest first. Empty if it is not this person's.

    The page needs this because a thread is now more than one turn: `?job=` names the
    run being watched, and the turns before it were never in this tab's memory. Empty
    rather than an exception for a thread that is not theirs — same answer as a thread
    that is not there, for the same reason as `forget_thread`.
    """
    async with session_scope() as session:
        repo = AppRepository(session)
        conversation = await repo.conversation_by_id(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            return []
        return await repo.reports_for_conversation(conversation_id)


async def forget_thread(user_id: int, conversation_id: int) -> bool:
    """Delete one thread and its runs. False if it is not this person's, or not there.

    The two cases are one answer on purpose: telling a caller that a thread exists but
    belongs to someone else is telling them something they did not have.
    """
    async with session_scope() as session:
        repo = AppRepository(session)
        return await repo.delete_conversation(conversation_id, user_id)
