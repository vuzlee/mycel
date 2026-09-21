"""Which threads a person has.

The sidebar cannot show a history without knowing whose it is. A query, so it answers
inside the request — same reason as `domains/dashboard`.

The other list a UI needs, which projects have data, moved to `domains/dashboard` when
Jira became the source: it is a gold question now, and it belongs beside the other one.
"""

from dataclasses import dataclass

from mycel.infra.postgres.repositories.app import AppRepository, ConversationRow
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
