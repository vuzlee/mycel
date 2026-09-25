"""What one agent run carries for its whole lifetime: job_id, budget, DB session, trace
context.

Passed as a parameter rather than a global, so agents running in parallel do not tread on
each other. A child agent gets the same budget object as its parent, so its tokens count
against the same ceiling.

**Named `deps`, not `run_context`.** pydantic-ai already has a `RunContext`, and it means
something different — what a *tool* receives (the framework's own per-call state), not what
a run carries. Two types with one name in the same call stack is a permanent confusion tax,
so this is `MycelDeps` and it arrives as `ctx.deps`.

No repeat-counter lives here: `guards.py` reads the real message history instead, which
cannot drift out of sync with what actually happened.
"""

from dataclasses import dataclass, field, replace

from mycel.agents.core.config import AgentSettings
from mycel.events.channel import EventChannel, NullChannel
from mycel.llm.budget import JobBudget
from mycel.services.auth import Principal


@dataclass
class MycelDeps:
    """Everything a run needs that is not the prompt.

    Handed to `Agent(deps_type=MycelDeps)` and reachable from every tool as `ctx.deps`.
    """

    job_id: str
    budget: JobBudget
    settings: AgentSettings = field(default_factory=AgentSettings)
    events: EventChannel = field(default_factory=NullChannel)

    #: Who asked. `None` is valid and means nobody — a smoke script, a test, a job whose
    #: payload predates this field. It is **not** a skeleton key: every tool that reads a
    #: team's data treats `None` as "granted nothing", so a path that forgets to pass a
    #: principal fails closed rather than opening the whole of gold.
    principal: Principal | None = None

    # session: AsyncSession — added when infra/ lands. Deliberately absent from this
    # slice, which computes rather than queries.

    def child(self) -> "MycelDeps":
        """Deps for a sub-agent.

        Same `job_id` and the **same budget object**, because money is a per-job quantity
        and a delegated call spends the same pot.
        """
        return replace(self)
