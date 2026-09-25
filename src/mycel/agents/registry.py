"""The list of agents `orchestrator.py` is allowed to use.

One place to declare them, so adding an agent is one line here and no change to any
manager.

**Classes, not instances.** `AGENTS` maps a name to a `BaseAgent` subclass rather than to
a live `Agent`, because a module-level agent is a shared mutable object: whichever test or
task overrides its model last wins, across everything else running in the same process.
`build()` costs one call and removes the whole class of problem.

The dict is keyed off each class's own `name`, so the registry cannot disagree with the
class about what an agent is called — and therefore cannot send it to read another agent's
`config/agents/<name>.yaml`.

**This is where the orchestrator is kept out of reach, not the directory tree.** It lives
in `agent/` with the specialists because it is one, so the only thing preventing a
specialist from delegating back to its own caller is that `build_toolset` in
`tools/delegate.py` names the specialists and nothing else.

`analyst`, `orchestrator`, `researcher` and `summariser` are here because they run.
`librarian` is not: it reads the knowledge base, which needs a vector store that does not
exist yet. An agent appears here when it has code and not
before, because a registry listing agents that cannot run is a lie told to the orchestrator.
"""

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from mycel.agents.agent.analyst import Analyst
from mycel.agents.agent.orchestrator import Orchestrator
from mycel.agents.agent.researcher import Researcher
from mycel.agents.agent.summariser import Summariser
from mycel.agents.core.base import BaseAgent
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.core.exceptions import ConfigError
from mycel.events.channel import EventChannel, NullChannel
from mycel.llm.budget import JobBudget
from mycel.services.auth import Principal

if TYPE_CHECKING:
    from pydantic_ai import Agent


_DECLARED: tuple[type[BaseAgent[Any]], ...] = (Analyst, Orchestrator, Researcher, Summariser)

AGENTS: dict[str, type[BaseAgent[Any]]] = {cls.name: cls for cls in _DECLARED}


def build(name: str, settings: AgentSettings | None = None) -> "Agent[MycelDeps, Any]":
    """Build one agent by name, or raise `ConfigError` naming what is available.

    The error lists the known names because the caller is usually a config string or a
    queue message, and "unknown agent 'analyts'" next to the real list is the difference
    between a one-second fix and a hunt.
    """
    try:
        agent_cls = AGENTS[name]
    except KeyError:
        known = ", ".join(sorted(AGENTS)) or "(none)"
        raise ConfigError(f"unknown agent {name!r}; known agents: {known}") from None
    return agent_cls.build(settings)


def build_deps(
    job_id: str,
    ceiling_usd: Decimal | str,
    settings: AgentSettings | None = None,
    budget: JobBudget | None = None,
    events: EventChannel | None = None,
    principal: Principal | None = None,
) -> MycelDeps:
    """Make the deps one job's runs share.

    Every run in a job must be handed the *same* `MycelDeps`, because the budget lives on
    it. Building fresh deps per run gives each run its own ceiling, which is not a budget
    at all — so this is called once per job, at the edge, and passed down.

    `ceiling_usd` accepts a string so callers can pass config values straight through
    without a float ever touching money.

    `budget` is for the caller that already knows what this job has spent — the worker,
    which reads the running total out of Redis so a redelivered job does not start again
    from zero. Left out, the job starts at its full ceiling, which is right for a script
    or a test and wrong for anything that can be retried.

    `principal` left out means nobody asked, which every tool that reads a team's data
    reads as "granted nothing". A script that needs real data builds a `Principal` and says
    so; the default is closed, because a forgotten argument must not be an open door.
    """
    return MycelDeps(
        job_id=job_id,
        budget=budget or JobBudget(job_id, Decimal(ceiling_usd)),
        settings=settings or AgentSettings(),
        events=events or NullChannel(),
        principal=principal,
    )
