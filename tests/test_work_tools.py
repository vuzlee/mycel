"""The ready-made work reads, against a real Postgres with the asker's project scope."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from mycel.agents.tools.work import build_toolset
from mycel.infra.postgres.engine import get_engine
from tests.test_query_tool import _AgainstTheDatabase, needs_postgres

pytestmark = pytest.mark.anyio


def _tool(name: str) -> Any:
    return build_toolset().tools[name].function


@needs_postgres
class TestWorkTools(_AgainstTheDatabase):
    async def _log(self, project: str, issue: str, author: str, hours: float) -> None:
        await self._seed(project, issue)
        async with get_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO gold.worklog (source, project, worklog_id, issue_key,"
                    " author_name, time_spent_seconds, started_at)"
                    " VALUES ('jira', :project, :id, :issue, :author, :seconds, now())"
                ),
                {
                    "project": project,
                    "id": f"{issue}-{author}",
                    "issue": issue,
                    "author": author,
                    "seconds": int(hours * 3600),
                },
            )

    async def test_hours_by_person_ranks_people_and_names_their_issues(self, ctx: Any) -> None:
        await self._log("MYC", "MYC-1", "ann", 5)
        await self._log("MYC", "MYC-2", "ann", 2)
        await self._log("MYC", "MYC-3", "bob", 3)

        out = await _tool("hours_by_person")(ctx, "this_month", 5)

        drawn = [e for e in ctx.deps.events.events if e.type == "chart"]
        assert drawn and drawn[0].payload["chart"]["labels"] == ["ann", "bob"]
        assert drawn[0].payload["chart"]["values"] == [7.0, 3.0]
        rows = out.splitlines()
        assert rows[0].startswith("author_name | total_hours | issues | issue_key | title")
        assert rows[1].startswith("ann | 7.00 | 2 | MYC-1 | dashboard | 5.00")
        assert any(r.startswith("bob | 3.00 | 1 | MYC-3") for r in rows)

    async def test_hours_by_person_keeps_to_the_granted_projects(self, ctx: Any) -> None:
        await self._log("MYC", "MYC-1", "ann", 1)
        await self._log("ACME", "ACME-1", "eve", 9)

        out = await _tool("hours_by_person")(ctx, "this_month", 5)

        assert "ann" in out and "eve" not in out

    async def test_late_items_lists_only_open_items_past_due(self, ctx: Any) -> None:
        await self._seed("MYC", "MYC-1")
        await self._seed("MYC", "MYC-2")
        past = datetime.now(UTC) - timedelta(days=3)
        async with get_engine().begin() as conn:
            await conn.execute(
                text(
                    "UPDATE gold.work_item SET due_at = :past, status_category = 'doing'"
                    " WHERE issue_key = 'MYC-1'"
                ),
                {"past": past},
            )
            await conn.execute(
                text("UPDATE gold.work_item SET due_at = :past WHERE issue_key = 'MYC-2'"),
                {"past": past},
            )

        out = await _tool("late_items")(ctx)

        assert "MYC-1" in out and "MYC-2" not in out

    async def test_open_epics_counts_open_children(self, ctx: Any) -> None:
        await self._seed("MYC", "MYC-1")
        await self._seed("MYC", "MYC-2")
        async with get_engine().begin() as conn:
            await conn.execute(
                text(
                    "UPDATE gold.work_item SET kind = 'epic', status_category = 'doing'"
                    " WHERE issue_key = 'MYC-1'"
                )
            )
            await conn.execute(
                text(
                    "UPDATE gold.work_item SET parent_key = 'MYC-1', status_category = 'todo'"
                    " WHERE issue_key = 'MYC-2'"
                )
            )

        out = await _tool("open_epics")(ctx)

        assert out.splitlines()[1].startswith("MYC-1 | dashboard | Done | 1 | 1")
