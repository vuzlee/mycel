"""Tool: run model-written read-only SQL on gold.

Access is enforced by Postgres: a read-only transaction as `mycel_reader`, with row-level
security scoped to the asker's granted projects. No principal means no rows.
`_reject`, `LIMIT` and the timeout only fail early; they are not the defense.
"""

import re
from collections.abc import Sequence
from typing import Any

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from mycel.agents.core.chip_filter import opens
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.guards import guard_repeat
from mycel.core.chips import Chip
from mycel.infra.postgres.acl import scoped_read
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


#: Said with every result: a model that doubts a table asks for it again.
COMPLETE = "That is every row this query returns. Answer from it."
EMPTY = "(no rows) Nothing matches, and that is the answer: report it and stop."
#: An aggregate over nothing is one row of NULLs, which models read as a broken query.
NOTHING = "Every value is empty: no rows matched, so the total is zero. That is the answer."


def table(columns: list[str], rows: Sequence[Sequence[Any]]) -> str:
    """Rows as a pipe-separated table. Empty says it is an answer, not a failed read."""
    if not rows:
        return f"{' | '.join(columns)}\n{EMPTY}"
    body = "\n".join(" | ".join("" if v is None else str(v) for v in row) for row in rows)
    return f"{' | '.join(columns)}\n{body}"


def final(columns: list[str], rows: Sequence[Sequence[Any]]) -> str:
    """The table and the line that tells the model it is the whole answer."""
    closing = _closing(rows)
    return f"{table(columns, rows)}\n{closing}" if closing else table(columns, rows)


def _closing(rows: Sequence[Sequence[Any]]) -> str:
    """The line after a table: what the model should take from it."""
    if rows and all(v is None for row in rows for v in row):
        return NOTHING
    return COMPLETE if rows else ""


def _same_query(args: dict[str, Any]) -> dict[str, Any]:
    """Whitespace, case and a trailing semicolon do not make a query new."""
    query = str(args.get("query", ""))
    return {"query": " ".join(query.rstrip().rstrip(";").split()).lower()}


async def _scope(deps: MycelDeps) -> str:
    """The asker's granted projects, comma-separated; read fresh so a revoke applies at once."""
    if deps.principal is None:
        return ""
    return ",".join(sorted(await readable_projects(deps.principal)))


class _Failed(Exception):
    """The query ran and Postgres refused it."""


async def read(deps: MycelDeps, query: str, params: dict[str, Any] | None = None) -> str:
    """One query as the asker: read-only, timed out, scoped to their projects, as a table."""
    columns, rows = await read_rows(deps, query, params)
    return table(columns, rows)


async def read_rows(
    deps: MycelDeps, query: str, params: dict[str, Any] | None = None
) -> tuple[list[str], Sequence[Sequence[Any]]]:
    """`read`, as columns and rows, for a caller that draws from them too."""
    scope = await _scope(deps)
    try:
        return await scoped_read(query, params or {}, scope, TIMEOUT_MS)
    except Exception as exc:
        raise _Failed(str(exc.__cause__ or exc)) from exc


def build_toolset() -> FunctionToolset[MycelDeps]:
    toolset: FunctionToolset[MycelDeps] = FunctionToolset(metadata=opens(Chip.JIRA))

    @toolset.tool(name="run_sql")
    async def _run_sql(ctx: RunContext[MycelDeps], query: str) -> str:
        """Run one read-only SELECT against the gold schema and return the rows.

        Args:
            query: One SELECT or WITH statement, no trailing semicolon. Tables are
                `gold.work_item` and `gold.worklog`. Add your own LIMIT when you want
                fewer than 200 rows.
        """
        guard_repeat(ctx, "run_sql", same=_same_query, query=query)
        if refusal := _reject(query):
            raise ModelRetry(refusal)
        try:
            columns, rows = await read_rows(ctx.deps, _limited(query))
        except _Failed as exc:
            # Bad SQL is a draft to fix; send the driver's underlying cause.
            raise ModelRetry(f"That query failed: {exc}. Fix it and retry.") from exc
        return final(columns, rows)

    return toolset
