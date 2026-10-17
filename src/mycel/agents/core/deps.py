from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.own_endpoint import OwnEndpoint
from mycel.core.chips import Chip
from mycel.core.principal import Principal
from mycel.events.channel import EventChannel, NullChannel
from mycel.llm.budget import JobBudget


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

    #: Set when the turn runs on a person's own model; every agent of the run uses it.
    own: OwnEndpoint | None = None

    #: The asker's zone, from their browser; what "now", "tonight" and a booking mean.
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))

    #: Every number a tool returned this turn, whole results not previews: what a chart
    #: the model writes is checked against.
    seen: set[float] = field(default_factory=set)

    @property
    def user_id(self) -> int | None:
        """Who the run acts for, or `None` when nobody is behind it."""
        return self.principal.id if self.principal else None
