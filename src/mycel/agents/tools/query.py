"""One tool: read gold with SQL the model wrote.

**Who is asking is enforced by Postgres, not by reading the query.** The model writes its
own SQL, and there is no reading of that SQL that tells you which rows it will touch — a
project can be named in a join, a subquery, a CTE, or not named at all by `SELECT *`. So
the transaction becomes `mycel_reader`, a role gold's row-level security applies to, and
scopes itself to the asker's granted projects with `SET LOCAL`. See
`infra/postgres/acl.py`. A query that asks for a project by name gets no rows rather than
an error, which is also the refusal that gives nothing away.

**No principal means no rows.** A run with `deps.principal` unset is scoped to the empty
list and reads nothing. That is the deliberate direction: a forgotten principal produces an
empty answer, never an open one.

**Four layers stop a write, and only one of them is real.** The prompt asks for SELECT,
`_reject` refuses anything that does not look like one, and `LIMIT` caps what comes back —
but a model that finds a phrasing none of those expect is stopped by `SET TRANSACTION READ
ONLY` and nothing else. The first three exist to fail early and say why, which is worth
having; they are not the defence.

`LIMIT` and `statement_timeout` are not security. A result crosses the context window, so
a full table scan is a bill rather than an answer, and a model-written join of three tables
can be a Cartesian product that never returns.

Rows come back as a text table, not JSON: a model reads a table at roughly half the tokens
for the same information.
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
    """The asker's granted projects, as the comma-separated list the policy splits.

    Empty for a run with no principal, which the policy reads as no rows. Read fresh each
    call rather than carried on the deps: a grant revoked mid-run should take effect on the
    next query, not at the end of the job.
    """
    if deps.principal is None:
        return ""
    return ",".join(sorted(await readable_projects(deps.principal)))


def build_toolset() -> FunctionToolset[MycelDeps]:
    """The gold-layer read, as a tool an agent can be given."""
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
            # The one layer Postgres enforces. Inside the same transaction as the query,
            # because a read-only setting on any other transaction protects nothing.
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await session.execute(text(f"SET LOCAL statement_timeout = {TIMEOUT_MS}"))
            # Scope first, role second. `SET ROLE` is the point of no return — after it
            # the connection can no longer set anything it is not allowed to — and a scope
            # set after the role would be a scope the policy never saw.
            #
            # `set_config(..., true)` rather than `SET LOCAL`: both are transaction-local,
            # but only the function form takes a bind parameter, and a project list pasted
            # into SQL is the injection this whole layer exists to avoid.
            await session.execute(
                text("SELECT set_config(:name, :scope, true)"),
                {"name": SCOPE_SETTING, "scope": scope},
            )
            await session.execute(text(f"SET LOCAL ROLE {READER_ROLE}"))
            try:
                result = await session.execute(text(_limited(query)))
            except Exception as exc:
                # Returned as a re-prompt: bad SQL is a draft to fix, not a dead run. The
                # driver wraps the real message, so the model gets the cause, not the wrapper.
                cause = exc.__cause__ or exc
                raise ModelRetry(f"That query failed: {cause}. Fix it and retry.") from exc
            return _table(list(result.keys()), result.fetchall())

    return toolset
