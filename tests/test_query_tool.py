"""`run_sql`, against a real Postgres — never a fake.

The whole point of this tool is a layer only Postgres enforces. A fake session would let
`SET TRANSACTION READ ONLY` pass as a no-op and every write test below would go green
while the real thing wrote to the database. So these skip without `DATABASE_URL` rather
than substitute something that cannot fail the way production can.

The string checks in `_reject` are tested separately and purely: they are an early, legible
error, not the defence, and mixing the two would suggest otherwise.
"""

import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic_ai import ModelRetry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.tools import query as query_tool
from mycel.agents.tools.query import MAX_ROWS, _limited, _reject, _table, build_toolset
from mycel.infra.postgres import acl
from mycel.infra.postgres.engine import async_dsn, dispose_engine, get_engine
from mycel.infra.postgres.models import Base
from mycel.llm.budget import JobBudget
from mycel.services.auth import Principal

pytestmark = pytest.mark.anyio

DSN = os.environ.get("DATABASE_URL", "")
needs_postgres = pytest.mark.skipif(not DSN, reason="no test database is reachable")

assert not DSN or DSN.rsplit("/", 1)[-1].endswith("_test"), f"refusing to run against {DSN}"

SCHEMAS = ("bronze", "silver", "gold", "app")


class TestWhatIsRefusedBeforeTheDatabase:
    """Pure string checks. Cheap, and they tell the model what to send instead."""

    def test_a_select_passes(self) -> None:
        assert _reject("SELECT 1") is None

    def test_a_cte_passes(self) -> None:
        """`WITH` is how an aggregate over a window gets written, so refusing it would
        push the model towards worse SQL."""
        assert _reject("WITH x AS (SELECT 1) SELECT * FROM x") is None

    @pytest.mark.parametrize(
        "write",
        ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "GRANT", "CREATE", "COPY"],
    )
    def test_a_write_as_the_first_word_is_refused(self, write: str) -> None:
        """Caught by the opening check, before the blocklist is even consulted."""
        refusal = _reject(f"{write} something")
        assert refusal is not None and "SELECT or WITH" in refusal

    @pytest.mark.parametrize(
        "write",
        ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "GRANT", "CREATE", "COPY"],
    )
    def test_a_write_hidden_behind_a_select_is_named_and_refused(self, write: str) -> None:
        """The case the blocklist is for, one keyword at a time: a hole in it passes
        silently, and the refusal has to say which word it objected to."""
        refusal = _reject(f"SELECT 1 FROM t WHERE x = (WITH q AS ({write} INTO t) SELECT 1)")
        assert refusal is not None and write in refusal

    def test_a_second_statement_is_refused(self) -> None:
        """The classic way a read becomes a write."""
        refusal = _reject("SELECT 1; DROP TABLE gold.work_item")
        assert refusal is not None and "one query" in refusal

    def test_a_trailing_semicolon_is_not_a_second_statement(self) -> None:
        """Punctuation, not an attack. Refusing it would teach the model nothing."""
        assert _reject("SELECT 1;") is None

    def test_a_column_named_like_a_keyword_is_not_a_write(self) -> None:
        """`updated_at` contains "update". Matching substrings would refuse most of gold."""
        assert _reject("SELECT updated_at, created_at FROM gold.work_item") is None


class TestTheRowCap:
    def test_a_query_without_a_limit_gets_one(self) -> None:
        assert f"LIMIT {MAX_ROWS}" in _limited("SELECT * FROM gold.work_item")

    def test_a_query_with_its_own_limit_keeps_it(self) -> None:
        """The model asking for 5 rows means 5, not 5 then 200."""
        limited = _limited("SELECT * FROM gold.work_item LIMIT 5")
        assert limited.endswith("LIMIT 5") and str(MAX_ROWS) not in limited


class TestTheTable:
    def test_rows_render_as_columns(self) -> None:
        assert _table(["a", "b"], [(1, 2)]) == "a | b\n1 | 2"

    def test_no_rows_says_so(self) -> None:
        """An empty string reads as a failed call, and a model retries what did not fail."""
        assert _table(["a"], []) == "a\n(no rows)"

    def test_null_is_blank_not_the_word_none(self) -> None:
        """Python's `None` in a table would be read back as a value."""
        assert _table(["a"], [(None,)]) == "a\n"


class _AgainstTheDatabase:
    """Schema, seeding and fixtures for everything only a real Postgres can answer.

    A base rather than a parent test class: inheriting one test class from another reruns
    every test in it, and these are the slowest in the file.
    """

    @pytest.fixture(autouse=True)
    async def schema(self, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
        """Gold, built and dropped, with the tool's own engine pointed at it.

        The tool opens its own `session_scope()` — that is the convention it breaks and
        the reason this fixture has to reach the process-wide engine rather than hand a
        session in.
        """
        monkeypatch.setenv("DATABASE_URL", DSN)
        await dispose_engine()
        engine = create_async_engine(async_dsn(DSN))
        async with engine.begin() as conn:
            for schema in SCHEMAS:
                await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
            await conn.run_sync(Base.metadata.create_all)
            # The same statements migration 0012 runs. The suite never runs alembic, so
            # without this the tool would step into a role the policies do not exist for —
            # and every row-filtering test below would pass by reading everything.
            await acl.apply(conn)
        await engine.dispose()
        try:
            yield
        finally:
            await dispose_engine()
            engine = create_async_engine(async_dsn(DSN))
            async with engine.begin() as conn:
                for schema in SCHEMAS:
                    await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            await engine.dispose()

    @pytest.fixture
    def run_sql(self) -> Any:
        return build_toolset().tools["run_sql"].function

    @pytest.fixture
    def granted(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """What the asker may read, without an `app.membership` behind it.

        A list the test mutates: the scope is read per call, so a revoke mid-run takes
        effect on the next query rather than at the end of the job.
        """
        projects: list[str] = ["MYC"]

        async def _readable(user: Any) -> frozenset[str]:
            return frozenset(projects)

        monkeypatch.setattr(query_tool, "readable_projects", _readable)
        return projects

    @pytest.fixture
    def ctx(self, granted: list[str]) -> Any:
        """Enough of a `RunContext` for `guard_repeat`: deps, and an empty history."""

        class _Ctx:
            deps = MycelDeps(
                job_id="job-1",
                budget=JobBudget("job-1", Decimal("1.00")),
                settings=AgentSettings(model_spec="local:qwen3-4b"),
                principal=Principal(id=1, email="someone@example.com"),
            )
            messages: list[Any] = []

        return _Ctx()

    async def _seed(self, project: str = "MYC", issue: str = "MYC-7") -> None:
        async with get_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO gold.work_item (source, project, issue_id, issue_key, kind,"
                    " title, status, status_category, labels, created_at, updated_at)"
                    " VALUES ('jira', :project, :id, :key, 'story', 'dashboard', 'Done',"
                    " 'done', '[]'::jsonb, :now, :now)"
                ),
                {
                    "project": project,
                    "id": issue.rsplit("-", 1)[-1],
                    "key": issue,
                    "now": datetime(2026, 9, 20, tzinfo=UTC),
                },
            )


@needs_postgres
class TestAgainstTheDatabase(_AgainstTheDatabase):
    """What the tool does against a real Postgres, for an asker granted MYC."""

    async def test_a_select_returns_a_table(self, run_sql: Any, ctx: Any) -> None:
        await self._seed()
        out = await run_sql(ctx, "SELECT issue_key, status FROM gold.work_item")
        assert "issue_key | status" in out and "MYC-7 | Done" in out

    async def test_an_empty_result_is_a_table_not_an_error(self, run_sql: Any, ctx: Any) -> None:
        out = await run_sql(ctx, "SELECT issue_key FROM gold.work_item WHERE project = 'NONE'")
        assert out == "issue_key\n(no rows)"

    async def test_the_row_cap_is_enforced_by_the_database(self, run_sql: Any, ctx: Any) -> None:
        """`_limited` adds the clause; this proves the clause reaches Postgres."""
        out = await run_sql(ctx, "SELECT g FROM generate_series(1, 500) g")
        assert len(out.splitlines()) == MAX_ROWS + 1

    async def test_a_write_that_slips_past_the_string_check_still_cannot_write(
        self, run_sql: Any, ctx: Any
    ) -> None:
        """The layer that matters, tested the only way it can be.

        `SELECT ... INTO` creates a table and opens with SELECT, so `_reject` lets it
        through. Postgres is what refuses it, which is the claim the whole tool rests on.
        """
        await self._seed()
        with pytest.raises(ModelRetry) as caught:
            await run_sql(ctx, "SELECT * INTO gold.stolen FROM gold.work_item")
        assert "read-only" in str(caught.value).lower()

        async with get_engine().connect() as conn:
            exists = await conn.scalar(text("SELECT to_regclass('gold.stolen')"))
        assert exists is None

    async def test_a_slow_query_is_cut_short_with_a_readable_error(
        self, run_sql: Any, ctx: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A model can write a three-table cross join without meaning to. The run must
        come back saying so rather than hold a connection until someone notices.

        The real cap is five seconds; the test shortens it so the suite does not wait it out.
        """
        monkeypatch.setattr(query_tool, "TIMEOUT_MS", 200)
        with pytest.raises(ModelRetry) as caught:
            await run_sql(ctx, "SELECT pg_sleep(3)")
        assert "timeout" in str(caught.value).lower()

    async def test_broken_sql_comes_back_as_a_reprompt(self, run_sql: Any, ctx: Any) -> None:
        """A draft to fix, not a dead run: the model gets the error and sends a new query."""
        with pytest.raises(ModelRetry) as caught:
            await run_sql(ctx, "SELECT nope FROM gold.work_item")
        assert "nope" in str(caught.value)

    async def test_a_refused_query_never_reaches_the_database(self, run_sql: Any, ctx: Any) -> None:
        """Refused as text, not raised: the model reads it and sends a read instead."""
        await self._seed()
        with pytest.raises(ModelRetry) as caught:
            await run_sql(ctx, "DELETE FROM gold.work_item")
        assert "SELECT or WITH" in str(caught.value)

        async with get_engine().connect() as conn:
            left = await conn.scalar(text("SELECT count(*) FROM gold.work_item"))
        assert left == 1


@needs_postgres
class TestOnlyTheProjectsTheAskerWasGranted(_AgainstTheDatabase):
    """The fault batch 055 closed, and the reason the filter is not in Python."""

    async def _two_projects(self) -> None:
        await self._seed("MYC", "MYC-7")
        await self._seed("ACME", "ACME-1")

    async def test_a_plain_select_only_returns_the_granted_project(
        self, run_sql: Any, ctx: Any
    ) -> None:
        """The query names no project and no user. Postgres filters it anyway, which is
        the whole reason the rule is a policy rather than something read off the SQL."""
        await self._two_projects()
        out = await run_sql(ctx, "SELECT issue_key FROM gold.work_item")
        assert "MYC-7" in out
        assert "ACME-1" not in out

    async def test_naming_another_project_outright_still_returns_nothing(
        self, run_sql: Any, ctx: Any
    ) -> None:
        """No rows rather than an error: a refusal that said "not allowed" would be a way
        of learning that ACME exists."""
        await self._two_projects()
        out = await run_sql(ctx, "SELECT issue_key FROM gold.work_item WHERE project = 'ACME'")
        assert out == "issue_key\n(no rows)"

    async def test_a_subquery_cannot_reach_around_it(self, run_sql: Any, ctx: Any) -> None:
        """A policy applies per table scan, so it applies inside a CTE too — which a
        filter bolted onto the outer query would not."""
        await self._two_projects()
        out = await run_sql(
            ctx,
            "WITH everything AS (SELECT issue_key, project FROM gold.work_item)"
            " SELECT issue_key FROM everything",
        )
        assert "MYC-7" in out and "ACME-1" not in out

    async def test_an_aggregate_cannot_count_what_it_cannot_read(
        self, run_sql: Any, ctx: Any
    ) -> None:
        """A count is a leak of exactly one number, and it leaks through the same scan."""
        await self._two_projects()
        out = await run_sql(ctx, "SELECT count(*) AS n FROM gold.work_item")
        assert out.endswith("\n1")

    async def test_a_run_with_nobody_attached_reads_nothing(self, run_sql: Any, ctx: Any) -> None:
        """`None` is closed. A path that forgot the principal gets an empty answer, never
        the whole of gold."""
        await self._two_projects()
        ctx.deps = replace(ctx.deps, principal=None)
        out = await run_sql(ctx, "SELECT issue_key FROM gold.work_item")
        assert out == "issue_key\n(no rows)"

    async def test_a_grant_taken_back_applies_to_the_next_query(
        self, run_sql: Any, ctx: Any, granted: list[str]
    ) -> None:
        """The scope is read per call, not carried on the deps: a revoke lands on the next
        query rather than at the end of a job that may run for minutes."""
        await self._two_projects()
        assert "MYC-7" in await run_sql(ctx, "SELECT issue_key FROM gold.work_item")

        granted.clear()
        out = await run_sql(ctx, "SELECT issue_key FROM gold.work_item WHERE issue_key <> 'x'")
        assert out == "issue_key\n(no rows)"
