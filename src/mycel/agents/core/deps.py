from dataclasses import dataclass, field

from mycel.agents.core.chips import Chip
from mycel.agents.core.config import AgentSettings
from mycel.events.channel import EventChannel, NullChannel
from mycel.llm.budget import JobBudget
from mycel.services.auth import Principal


@dataclass
class MycelDeps:
    """Per-run state, reachable from every tool as `ctx.deps`."""

    job_id: str
    budget: JobBudget
    settings: AgentSettings = field(default_factory=AgentSettings)
    events: EventChannel = field(default_factory=NullChannel)

    #: Who asked. `None` means nobody and is granted nothing (fails closed).
    principal: Principal | None = None

    #: Chips picked this turn. `None` keeps every tool; an empty set keeps none.
    chips: "frozenset[Chip] | None" = None
