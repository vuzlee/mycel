"""Tool: run model-written read-only SQL on gold.

Access is enforced by Postgres: a read-only transaction as `mycel_reader`, with row-level
security scoped to the asker's granted projects. No principal means no rows.
`_reject`, `LIMIT` and the timeout only fail early; they are not the defense.
"""

import re
from collections.abc import Sequence
from typing import Any

from pydantic_ai import FunctionToolset, ModelRetry, RunContext
from sqlalchemy import text

from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.guards import guard_repeat
from mycel.infra.postgres.acl import READER_ROLE, SCOPE_SETTING
from mycel.infra.postgres.session import session_scope
from mycel.services.permission import readable_projects

MAX_ROWS = 200
TIMEOUT_MS = 5_000

#: Matched as whole words, so `updated_at` is not read as an UPDATE.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|create|copy|call|do)\b",
    re.IGNORECASE,
)
_OPENS_READ = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def _reject(query: str) -> str | None:
    """Why this query will not be run, or None. Phrased for the model to act on."""
    if not _OPENS_READ.match(query):
        return "Only a query starting with SELECT or WITH can be run. Rewrite it as a read."
    if ";" in query.rstrip().rstrip(";"):
        return "Only one statement per call. Remove the semicolon and send one query."
    if found := _FORBIDDEN.search(query):
        return f"{found.group(0).upper()} cannot be run here — gold is read-only. Ask for a read."
    return None


def _limited(query: str) -> str:
    """The query with a LIMIT, added only when it does not set its own."""
    stripped = query.rstrip().rstrip(";")
    if re.search(r"\blimit\b\s+\d+\s*$", stripped, re.IGNORECASE):
        return stripped
    return f"{stripped}\nLIMIT {MAX_ROWS}"


def _table(columns: list[str], rows: Sequence[Sequence[Any]]) -> str:
    """Rows as a pipe-separated table. Empty says so rather than returning nothing."""
    if not rows:
        return f"{' | '.join(columns)}\n(no rows)"
    body = "\n".join(" | ".join("" if v is None else str(v) for v in row) for row in rows)
    return f"{' | '.join(columns)}\n{body}"


async def _scope(deps: MycelDeps) -> str:
    """The asker's granted projects, comma-separated; read fresh so a revoke applies at once."""
    if deps.principal is None:
        return ""
    return ",".join(sorted(await readable_projects(deps.principal)))


def build_toolset() -> FunctionToolset[MycelDeps]:
    toolset: FunctionToolset[MycelDeps] = FunctionToolset()

    @toolset.tool(name="run_sql")
    async def _run_sql(ctx: RunContext[MycelDeps], query: str) -> str:
        """Run one read-only SELECT against the gold schema and return the rows.

        Args:
            query: One SELECT or WITH statement, no trailing semicolon. Tables are
                `gold.work_item` and `gold.worklog`. Add your own LIMIT when you want
                fewer than 200 rows.
        """
        guard_repeat(ctx, "run_sql", threshold=ctx.deps.settings.repeat_threshold, query=query)
        if refusal := _reject(query):
            raise ModelRetry(refusal)
        scope = await _scope(ctx.deps)
        async with session_scope() as session:
            # Must be the query's own transaction to protect anything.
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await session.execute(text(f"SET LOCAL statement_timeout = {TIMEOUT_MS}"))
            # Scope before role: after `SET ROLE` the scope can no longer be set.
            # `set_config` rather than `SET LOCAL` so the scope is a bind parameter.
            await session.execute(
                text("SELECT set_config(:name, :scope, true)"),
                {"name": SCOPE_SETTING, "scope": scope},
            )
            await session.execute(text(f"SET LOCAL ROLE {READER_ROLE}"))
            try:
                result = await session.execute(text(_limited(query)))
            except Exception as exc:
                # Bad SQL is a draft to fix; send the driver's underlying cause.
                cause = exc.__cause__ or exc
                raise ModelRetry(f"That query failed: {cause}. Fix it and retry.") from exc
            return _table(list(result.keys()), result.fetchall())

    return toolset
