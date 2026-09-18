"""Coordinating agent: takes a report request, splits it into tasks, assigns them to
specialist agents, merges the results.

It does not analyse figures or write prose itself — it decides *what is needed* and hands
the work out. Independent tasks run in parallel; if one fails the report still comes out,
with the gap stated explicitly rather than invented.

Not called "manager" to avoid confusion with `managers/` — that one is the per-domain HTTP
entry point.

**Specialists are tools, not a pipeline.** `ask_researcher` and `ask_analyst` are ordinary
tools whose bodies call `runner.delegate`, so the model chooses which to call and how many
times, in the order the question needs. Hard-coding "research, then analyse" would be a
guess about a question nobody has asked yet.

**Delegation, not handoff.** `runner.delegate` forwards `usage=ctx.usage`, which merges a
specialist's tokens into this run's usage — so the single `record()` at the end of the
orchestrator's own run already bills every delegated token. That is also why neither tool
calls `budget.record()`: doing so would charge the same tokens twice. See `core/runner.py`.

**A failing specialist is a gap, not a dead run.** Each tool catches `AgentError` and
returns the failure as text the model can read. Letting it propagate would kill a report
over one unavailable source, which is exactly the outcome the docstring above rules out.
`BudgetExceeded` is deliberately *not* caught: out of money is the end of the job, and
continuing would spend money the job does not have.
"""

from typing import Any, cast

from pydantic import BaseModel, Field
from pydantic_ai import RunContext
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from mycel.agents.agent.analyst import Analyst
from mycel.agents.agent.researcher import Researcher
from mycel.agents.core import runner
from mycel.agents.core.base import BaseAgent
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import AgentError
from mycel.agents.prompts import load
from mycel.core.logging import get_logger

log = get_logger(__name__)


class Finding(BaseModel):
    """One thing the report says, and who established it."""

    statement: str = Field(description="One thing that is true, stated plainly.")
    sources: list[str] = Field(
        default_factory=list,
        description=(
            "Urls or tool calls the specialist cited for this statement, copied through "
            "unchanged. Never invent one."
        ),
    )


class Report(BaseModel):
    """What the orchestrator hands back: the merged answer, holes included."""

    findings: list[Finding] = Field(description="What the specialists established.")
    gaps: list[str] = Field(
        default_factory=list,
        description=(
            "What was asked but could not be answered, including work a specialist failed "
            "to do. A stated hole is a finding; a filled-in guess is not."
        ),
    )


def build_toolset(settings: AgentSettings | None = None) -> FunctionToolset[MycelDeps]:
    """The specialists, as tools this agent may call.

    `settings` configures the *orchestrator*; each specialist reads its own
    `config/agents/<name>.yaml`, because a sub-agent's model and limits are its own
    property rather than something inherited from whoever called it.
    """
    toolset: FunctionToolset[MycelDeps] = FunctionToolset()

    @toolset.tool(name="ask_researcher")
    async def _ask_researcher(ctx: RunContext[MycelDeps], question: str) -> str:
        """Ask the researcher to find out what is currently true, with urls.

        Args:
            question: One self-contained question. The researcher cannot see this run's
                prompt or any earlier answer.
        """
        return await _delegate(ctx, Researcher, "researcher", question)

    @toolset.tool(name="ask_analyst")
    async def _ask_analyst(ctx: RunContext[MycelDeps], question: str) -> str:
        """Ask the analyst to compute over figures and report what they show.

        Args:
            question: One self-contained question **including the numbers**. The analyst
                cannot see this run's prompt.
        """
        return await _delegate(ctx, Analyst, "analyst", question)

    return toolset


async def _delegate(
    ctx: RunContext[MycelDeps],
    agent_cls: type[BaseAgent[Any]],
    name: str,
    question: str,
) -> str:
    """Run one specialist on the caller's budget, returning its failure rather than raising.

    The output is serialised to JSON because a tool result goes back to the model as text:
    the specialist's schema is what keeps statements attached to their sources across that
    boundary.
    """
    cfg = AgentSettings.from_config(name)
    try:
        output = await runner.delegate(agent_cls.build(cfg), question, ctx, cfg)
    except AgentError as exc:
        # Returned, not raised: see the module docstring. `BudgetExceeded` is not an
        # `AgentError` and so passes through, ending the job as it should.
        log.warning("specialist failed", extra={"agent": name, "error": str(exc)})
        return f"{name} could not answer: {exc}. Record this as a gap and continue."
    # Every specialist's output_type is a `BaseModel`, but `BaseAgent` is generic over
    # plain objects, so the guarantee is ours to state rather than the type system's.
    return cast(str, output.model_dump_json())


class Orchestrator(BaseAgent[Report]):
    """Splits a request across the specialists and merges what they return."""

    name = "orchestrator"
    instructions = load("orchestrator")
    output_type = Report

    @classmethod
    def toolsets(cls) -> list[AbstractToolset[MycelDeps]]:
        return [build_toolset()]
