"""The list of agents `orchestrator.py` is allowed to use.

One place to declare them, so adding an agent is one line here and no change to any
manager.

**Builders, not instances.** `AGENTS` maps a name to a factory rather than to a live
`Agent`, because a module-level agent is a shared mutable object: whichever test or task
overrides its model last wins, across everything else running in the same process. A
factory costs one call and removes the whole class of problem.

Only `analyst` exists so far. `writer` and `reviewer` are docstring-only modules; they
appear here when they have code, not before — a registry that lists agents which cannot
run is a lie told to the orchestrator.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from mycel.agents.analyst import build_analyst
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.core.exceptions import ConfigError
from mycel.llm.budget import JobBudget

if TYPE_CHECKING:
    from pydantic_ai import Agent

AgentBuilder = Callable[[AgentSettings | None], "Agent[MycelDeps, Any]"]

AGENTS: dict[str, AgentBuilder] = {
    "analyst": build_analyst,
}


def build(name: str, settings: AgentSettings | None = None) -> "Agent[MycelDeps, Any]":
    """Build one agent by name, or raise `ConfigError` naming what is available.

    The error lists the known names because the caller is usually a config string or a
    queue message, and "unknown agent 'analyts'" next to the real list is the difference
    between a one-second fix and a hunt.
    """
    try:
        builder = AGENTS[name]
    except KeyError:
        known = ", ".join(sorted(AGENTS)) or "(none)"
        raise ConfigError(f"unknown agent {name!r}; known agents: {known}") from None
    return builder(settings)


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
