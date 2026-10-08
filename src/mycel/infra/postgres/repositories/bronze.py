"""Write raw provider payloads, untransformed, so later stages can be replayed."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import JiraIssue, JiraWorklog


class BronzeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_issues(self, issues: Sequence[dict[str, Any]]) -> int:
        """Store issues under Jira's `id`, overwriting older fetches."""
        rows = [
            {"issue_id": str(i["id"]), "issue_key": i["key"], "payload": i}
            for i in issues
            if i.get("id") and i.get("key")
        ]
        return await self._upsert(JiraIssue, rows, "issue_id")

    async def save_worklogs(self, key: str, worklogs: Sequence[dict[str, Any]]) -> int:
        """Store one issue's logged entries under Jira's own worklog id."""
        rows = [
            {"worklog_id": str(w["id"]), "issue_key": key, "payload": w}
            for w in worklogs
            if w.get("id")
        ]
        return await self._upsert(JiraWorklog, rows, "worklog_id")

    async def issue_payloads(self, keys: Sequence[str] | None = None) -> list[dict[str, Any]]:
        """Stored issue payloads; `keys` narrows to one sync, none means all."""
        query = select(JiraIssue.payload).order_by(JiraIssue.issue_id)
        if keys is not None:
            query = query.where(JiraIssue.issue_key.in_(keys))
        return [dict(p) for p in (await self._session.scalars(query)).all()]

    async def worklog_payloads(self, keys: Sequence[str] | None = None) -> list[dict[str, Any]]:
        """Stored worklogs with their issue key, which the payload itself lacks."""
        query = select(JiraWorklog.issue_key, JiraWorklog.payload).order_by(JiraWorklog.worklog_id)
        if keys is not None:
            query = query.where(JiraWorklog.issue_key.in_(keys))
        rows = (await self._session.execute(query)).all()
        return [{**dict(payload), "issue_key": key} for key, payload in rows]

    async def _upsert(self, table: Any, rows: list[dict[str, Any]], key: str) -> int:
        if not rows:
            return 0
        stmt = insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[key],
            set_={"payload": stmt.excluded.payload, "fetched_at": stmt.excluded.fetched_at},
        )
        await self._session.execute(stmt)
        return len(rows)
