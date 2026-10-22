"""Write raw provider payloads, untransformed, so later stages can be replayed."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mycel.infra.postgres.models import JiraIssue, JiraWorklog
from mycel.infra.postgres.repositories._sql import chunks


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
        return await self.save_all_worklogs({key: worklogs})

    async def save_all_worklogs(self, by_key: Mapping[str, Sequence[dict[str, Any]]]) -> int:
        """Store many issues' worklogs in chunked upserts, not one INSERT per issue."""
        rows = [
            {"worklog_id": str(w["id"]), "issue_key": key, "payload": w}
            for key, worklogs in by_key.items()
            for w in worklogs
            if w.get("id")
        ]
        return await self._upsert(JiraWorklog, rows, "worklog_id")

    async def keys_fetched_since(self, since: datetime | None) -> list[str]:
        """Issue keys written at or after `since`; every key when there is no mark yet."""
        query = select(JiraIssue.issue_key)
        if since is not None:
            query = query.where(JiraIssue.fetched_at >= since)
        return list((await self._session.scalars(query)).all())

    async def last_fetched_per_project(self) -> dict[str, datetime]:
        """When bronze last heard of each project. A project absent here is read in full."""
        project = JiraIssue.payload["fields"]["project"]["key"].astext
        rows = await self._session.execute(
            select(project, func.max(JiraIssue.fetched_at)).group_by(project)
        )
        return {str(p): stamp for p, stamp in rows.all() if p}

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
        for chunk in chunks(rows):
            stmt = insert(table).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=[key],
                set_={"payload": stmt.excluded.payload, "fetched_at": stmt.excluded.fetched_at},
            )
            await self._session.execute(stmt)
        return len(rows)
