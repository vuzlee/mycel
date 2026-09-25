"""Tools whose capability is another agent.

**A tool that wraps an agent carries that agent's name.** `researcher`, `analyst`,
`summariser` — the same string as the class's `name`, the same string as its
`config/agents/<name>.yaml`, so one grep reaches all three. The old names were
`ask_researcher` and `ask_analyst`; the fault was `ask_`, which reads as a chain of
command. There is none. The four agents differ in capability, and the orchestrator running
first is a choice of flow rather than a rank.

Wrapping is not a design choice: pydantic-ai cannot hand an `Agent` to an `Agent` — `Agent`
is not an `AbstractToolset` and there is no `as_tool()` — and a model can call tools and
nothing else. Calling `runner.delegate` in a tool body is the only route the library
offers, and `ask_` used to conflate that constraint with a hierarchy.

**Delegation, not handoff.** `runner.delegate` forwards `usage=ctx.usage`, which merges a
delegated agent's tokens into the caller's — so the single `record()` at the end of the
calling run already bills every delegated token. That is also why nothing here calls
`budget.record()`: doing so would charge the same tokens twice. See `core/runner.py`.

**A failing delegation is reported, not a dead run — unless nothing was reached.** The line
is not "did it raise", it is "is this an answer". A tool with no data, a schema the model
could not fill, a loop making no progress: poor answers, but answers, and the caller
narrates them. A `TransportError` is not an answer. The request never reached a model, and
the only thing that changes the outcome is trying again later, so it propagates and the job
fails — which is the retry path `queue/retry.py` exists to run.

Catching it too was a real outage: on 2026-09-24 a 503 inside the analyst came back as
"the work data analysis service encountered a 503 error", the job was marked done, billed,
written into the thread, and never retried. A crash is visible; that paragraph has to be
*read* to notice it says nothing.

`BudgetExceeded` is deliberately not caught either: out of money is the end of the job, and
continuing would spend money the job does not have.

This is the one tool module that imports from `agents/agent/`, which is what makes it the
only place the dependency exists — every other module gets delegation by asking for this
toolset rather than by importing an agent.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from mycel.agents.agent.analyst import Analyst
from mycel.agents.agent.researcher import Researcher
from mycel.agents.agent.summariser import Summariser
from mycel.agents.core import runner
from mycel.agents.core.base import BaseAgent
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import AgentError, ToolFailed, TransportError
from mycel.core.logging import get_logger
from mycel.infra.postgres.session import session_scope
from mycel.services.analyze import render
from mycel.services.gather import gather_progress
from mycel.services.permission import can_read_project

log = get_logger(__name__)

DEFAULT_WINDOW_DAYS = 7


def build_toolset(settings: AgentSettings | None = None) -> FunctionToolset[MycelDeps]:
    """The agents, as tools another agent may be given.

    Not the orchestrator's private toolbox: whichever agent a flow puts first gets this
    toolset, and a flow may give it to more than one.

    `settings` configures the *caller*; each delegated agent reads its own
    `config/agents/<name>.yaml`, because a delegated agent's model and limits are its own
    property rather than something inherited from whoever called it.
    """
    toolset: FunctionToolset[MycelDeps] = FunctionToolset()

    @toolset.tool(name="researcher")
    async def _researcher(ctx: RunContext[MycelDeps], question: str) -> str:
        """Find out what is currently true about a topic, with urls.

        Args:
            question: One self-contained question. The researcher cannot see this run's
                prompt or any earlier answer.
        """
        return await _delegate(ctx, Researcher, "researcher", question)

    @toolset.tool(name="analyst")
    async def _analyst(ctx: RunContext[MycelDeps], question: str) -> str:
        """Read the work data and report what the numbers show, each with its source.

        Args:
            question: One self-contained question. The analyst reads gold itself, so ask
                in plain words; include any numbers of your own that it should use.
        """
        return await _delegate(ctx, Analyst, "analyst", question)

    @toolset.tool(name="summariser")
    async def _summariser(
        ctx: RunContext[MycelDeps], project: str, days: int = DEFAULT_WINDOW_DAYS
    ) -> str:
        """Summarise a project's recent progress: shipped, in flight, late, load per person.

        Args:
            project: The project key, e.g. "MYC".
            days: How far back the window reaches. Defaults to a week.
        """
        await _must_read(ctx, project)
        until = datetime.now(UTC)
        async with session_scope() as session:
            window = await gather_progress(session, project, until - timedelta(days=days), until)
        return await _delegate(ctx, Summariser, "summariser", render(window))

    return toolset


#: Said for a project that does not exist and for one the asker was never granted, on
#: purpose. Two different sentences would turn this tool into a way of finding out which
#: projects exist by asking about them one at a time.
_NO_SUCH_PROJECT = "project {project} does not exist or you do not have access to it"


async def _must_read(ctx: RunContext[MycelDeps], project: str) -> None:
    """Stop before reading, or raise `ToolFailed`.

    `ToolFailed` rather than `ModelRetry`: not being granted a project is not a wrong
    argument the model can fix, and a retry is an invitation to try project names until one
    lands.

    No principal is no access. A run with nobody attached reads nothing here, the same as
    `run_sql` — see `agents/core/deps.py` for why `None` is closed rather than open.
    """
    user = ctx.deps.principal
    if user is None or not await can_read_project(user, project):
        log.info("project read refused", extra={"project": project, "job_id": ctx.deps.job_id})
        raise ToolFailed("summariser", _NO_SUCH_PROJECT.format(project=project))


async def _delegate(
    ctx: RunContext[MycelDeps],
    agent_cls: type[BaseAgent[Any]],
    name: str,
    prompt: str,
) -> str:
    """Run one delegated agent on the caller's budget.

    A failure that is an answer comes back as text. A `TransportError` is re-raised, so the
    job fails and the queue can retry it.

    The output is serialised to JSON because a tool result goes back to the model as text:
    the delegated agent's schema is what keeps statements attached to their sources across
    that boundary.
    """
    cfg = AgentSettings.from_config(name)
    try:
        output = await runner.delegate(agent_cls.build(cfg), prompt, ctx, cfg)
    except TransportError:
        # Raised before the clause below can swallow it: nothing was reached, so there is
        # nothing to narrate, and a retry is the only thing that changes the outcome.
        log.warning("delegated agent could not reach its model", extra={"agent": name})
        raise
    except AgentError as exc:
        # Returned, not raised: see the module docstring. `BudgetExceeded` is not an
        # `AgentError` and so passes through, ending the job as it should.
        log.warning("delegated agent failed", extra={"agent": name, "error": str(exc)})
        return f"{name} could not answer: {exc}. Say so in the answer and continue."
    # Every delegated agent's output_type is a `BaseModel`, but `BaseAgent` is generic over
    # plain objects, so the guarantee is ours to state rather than the type system's.
    return cast(str, output.model_dump_json())
