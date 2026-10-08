"""Tools that delegate to a specialist agent, named after it.

A failed delegation returns text the caller can narrate, except `TransportError` and
`BudgetExceeded`, which propagate so the job fails (and can be retried).
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from mycel.agents.core import runner
from mycel.agents.core.base import BaseAgent
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import AgentError, ToolFailed, TransportError
from mycel.agents.specialists.analyst import Analyst
from mycel.agents.specialists.researcher import Researcher
from mycel.agents.specialists.summarizer import Summarizer
from mycel.core.logging import get_logger
from mycel.infra.postgres.session import session_scope
from mycel.services.analyze import render
from mycel.services.gather import gather_progress
from mycel.services.permission import NotReadable, require

log = get_logger(__name__)

DEFAULT_WINDOW_DAYS = 7


def build_toolset() -> FunctionToolset[MycelDeps]:
    """The specialists as tools. Each reads its own config/agents/<name>.yaml."""
    toolset: FunctionToolset[MycelDeps] = FunctionToolset()

    @toolset.tool(name="researcher")
    async def _researcher(ctx: RunContext[MycelDeps], question: str) -> str:
        """Find out what is currently true about a topic, with urls.

        Args:
            question: One self-contained question. The researcher cannot see this run's
                prompt or any earlier answer.
        """
        return await _delegate(ctx, Researcher, question)

    @toolset.tool(name="analyst")
    async def _analyst(ctx: RunContext[MycelDeps], question: str) -> str:
        """Read the work data and report what the numbers show, each with its source.

        Args:
            question: One self-contained question. The analyst reads gold itself, so ask
                in plain words; include any numbers of your own that it should use.
        """
        return await _delegate(ctx, Analyst, question)

    @toolset.tool(name="summarizer")
    async def _summarizer(
        ctx: RunContext[MycelDeps], project: str, days: int = DEFAULT_WINDOW_DAYS
    ) -> str:
        """Summarize a project's recent progress: shipped, in flight, late, load per person.

        Args:
            project: The project key, e.g. "PROJ".
            days: How far back the window reaches. Defaults to a week.
        """
        await _require_readable(ctx, project)
        until = datetime.now(UTC)
        async with session_scope() as session:
            window = await gather_progress(session, project, until - timedelta(days=days), until)
        return await _delegate(ctx, Summarizer, render(window))

    return toolset


async def _require_readable(ctx: RunContext[MycelDeps], project: str) -> None:
    """Raise `ToolFailed` unless the asker may read `project`; no principal reads nothing."""
    try:
        await require(ctx.deps.principal, project)
    except NotReadable as exc:
        log.info("project read refused", extra={"project": project, "job_id": ctx.deps.job_id})
        raise ToolFailed("summarizer", str(exc)) from None


async def _delegate(
    ctx: RunContext[MycelDeps],
    agent_cls: type[BaseAgent[Any]],
    prompt: str,
) -> str:
    """Run one delegated agent on the caller's budget; output goes back as JSON."""
    name = agent_cls.name
    cfg = AgentSettings.from_config(name)
    try:
        output = await runner.delegate(agent_cls.build(cfg), prompt, ctx, cfg)
    except TransportError:
        log.warning("delegated agent could not reach its model", extra={"agent": name})
        raise
    except AgentError as exc:
        log.warning("delegated agent failed", extra={"agent": name, "error": str(exc)})
        return f"{name} could not answer: {exc}. Say so in the answer and continue."
    # Every delegated output_type is a `BaseModel`; the generic cannot say so.
    return cast(str, output.model_dump_json())
