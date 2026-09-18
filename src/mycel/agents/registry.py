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

`analyst`, `orchestrator` and `researcher` are here because they run. `librarian` is not:
it reads the knowledge base, which needs `storage/` and a gold layer that do not exist
yet — see `notes/deferred.md`. An agent appears here when it has code and not before,
because a registry listing agents that cannot run is a lie told to the orchestrator.
"""

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from mycel.agents.agent.analyst import Analyst
from mycel.agents.agent.researcher import Researcher
from mycel.agents.core.base import BaseAgent
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.orchestrator import Orchestrator
from mycel.core.exceptions import ConfigError
from mycel.llm.budget import JobBudget

if TYPE_CHECKING:
    from pydantic_ai import Agent


_DECLARED: tuple[type[BaseAgent[Any]], ...] = (Analyst, Orchestrator, Researcher)

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
) -> MycelDeps:
    """Make the deps one job's runs share.

    Every run in a job must be handed the *same* `MycelDeps`, because the budget lives on
    it. Building fresh deps per run gives each run its own ceiling, which is not a budget
    at all — so this is called once per job, at the edge, and passed down.

    `ceiling_usd` accepts a string so callers can pass config values straight through
    without a float ever touching money.
    """
    return MycelDeps(
        job_id=job_id,
        budget=JobBudget(job_id, Decimal(ceiling_usd)),
        settings=settings or AgentSettings(),
    )
