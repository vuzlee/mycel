"""Tool: similarity search over work items, scoped to the asker's granted projects."""

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import ToolFailed
from mycel.agents.core.guards import guard_repeat
from mycel.core.logging import get_logger
from mycel.infra.vectors import search as vectors
from mycel.infra.vectors.client import VectorsUnavailable
from mycel.services.permission import readable_projects

log = get_logger(__name__)

#: Past this a search is a listing, and SQL lists better.
MAX_RESULTS = 20


def build_toolset() -> FunctionToolset[MycelDeps]:
    toolset: FunctionToolset[MycelDeps] = FunctionToolset()

    @toolset.tool(name="rag_search")
    async def _rag_search(
        ctx: RunContext[MycelDeps],
        query: str,
        limit: int = 5,
        status_category: str | None = None,
    ) -> str:
        """Find work items by meaning: topic, symptom, or subject rather than exact words.

        Use it when the question is about a subject nobody wrote in a column — "anything
        about flaky logins", "what work touched the payment flow". For anything a filter
        can express — one status, one sprint, a date range, a count — use run_sql instead:
        it is exact, and this is not.

        Results are ordered by similarity and every one carries its issue key; cite them.
        A low score means the nearest thing found, not a thing that matches.

        Args:
            query: What the work would be about, in words. A phrase beats a keyword.
            limit: How many to return. Five is usually enough; twenty is the most.
            status_category: Optionally narrow to `todo`, `doing` or `done`.
        """
        guard_repeat(ctx, "rag_search", threshold=ctx.deps.settings.repeat_threshold, query=query)

        if not query.strip():
            raise ModelRetry("rag_search needs something to search for.")
        if limit < 1:
            raise ModelRetry("rag_search needs a limit of at least one.")

        principal = ctx.deps.principal
        # No principal is granted nothing: fail closed.
        projects = sorted(await readable_projects(principal)) if principal else []

        capped = min(limit, MAX_RESULTS)
        try:
            hits = await vectors.search(
                query, projects=projects, limit=capped, status_category=status_category
            )
        except VectorsUnavailable as exc:
            raise ToolFailed("rag_search", str(exc)) from exc

        return _render(hits, query=query, asked=limit, capped=capped, scoped=bool(projects))

    return toolset


def _render(hits: list[vectors.Hit], query: str, asked: int, capped: int, scoped: bool) -> str:
    """The hits as quotable text; "no access" and "no match" stay distinguishable."""
    if not scoped:
        return "No projects are readable by whoever is asking, so nothing was searched."
    if not hits:
        return f"Nothing indexed is close to {query!r}."

    lines = [f"{len(hits)} nearest to {query!r}, closest first."]
    if capped < asked:
        lines.append(f"({asked} was asked for; {MAX_RESULTS} is the most this returns.)")
    lines.append("Columns: score | key | status | type | assignee | sprint | title")
    for hit in hits:
        lines.append(
            f"{hit.score:.3f} | {hit.issue_key} | {hit.status} | {hit.kind} | "
            f"{hit.assignee_name or '-'} | {hit.sprint_name or '-'} | {hit.title}"
        )
    return "\n".join(lines)
