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
from mycel.infra.postgres.engine import async_dsn, dispose_engine, get_engine
from mycel.infra.postgres.models import Base
from mycel.llm.budget import JobBudget

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


@needs_postgres
class TestAgainstTheDatabase:
    """The half that only a real Postgres can answer."""

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
    def ctx(self) -> Any:
        """Enough of a `RunContext` for `guard_repeat`: deps, and an empty history."""

        class _Ctx:
            deps = MycelDeps(
                job_id="job-1",
                budget=JobBudget("job-1", Decimal("1.00")),
                settings=AgentSettings(model_spec="local:qwen3-4b"),
            )
            messages: list[Any] = []

        return _Ctx()

    async def _seed(self) -> None:
        async with get_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO gold.work_item (source, project, issue_id, issue_key, kind,"
                    " title, status, status_category, labels, created_at, updated_at)"
                    " VALUES ('jira', 'MYC', '7', 'MYC-7', 'story', 'dashboard', 'Done',"
                    " 'done', '[]'::jsonb, :now, :now)"
                ),
                {"now": datetime(2026, 9, 20, tzinfo=UTC)},
            )

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
