"""Registry of runnable agents, keyed by each class's own `name`."""

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from mycel.agents.core.base import BaseAgent
from mycel.agents.core.chips import Chip
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.specialists.analyst import Analyst
from mycel.agents.specialists.orchestrator import Orchestrator
from mycel.agents.specialists.researcher import Researcher
from mycel.agents.specialists.rewriter import Rewriter
from mycel.agents.specialists.summarizer import Summarizer
from mycel.core.exceptions import ConfigError
from mycel.events.channel import EventChannel, NullChannel
from mycel.llm.budget import JobBudget
from mycel.services.auth import Principal

if TYPE_CHECKING:
    from pydantic_ai import Agent


_DECLARED: tuple[type[BaseAgent[Any]], ...] = (
    Analyst,
    Orchestrator,
    Researcher,
    Rewriter,
    Summarizer,
)

AGENTS: dict[str, type[BaseAgent[Any]]] = {cls.name: cls for cls in _DECLARED}


def build(name: str, settings: AgentSettings | None = None) -> "Agent[MycelDeps, Any]":
    """Build one agent by name, or raise `ConfigError` listing the known names."""
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
    chips: "frozenset[Chip] | None" = None,
) -> MycelDeps:
    """Make the deps shared by every run in one job; call once per job so the budget is shared.

    `budget` carries what a retried job already spent. `principal=None` is granted nothing.
    """
    return MycelDeps(
        job_id=job_id,
        budget=budget or JobBudget(job_id, Decimal(ceiling_usd)),
        settings=settings or AgentSettings(),
        events=events or NullChannel(),
        principal=principal,
        chips=chips,
    )
