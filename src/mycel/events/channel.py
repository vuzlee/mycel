"""Where a run sends its events."""

from typing import Protocol

from mycel.events.event import AgentEvent


class EventChannel(Protocol):
    """A sink for one job's events."""

    async def publish(self, event: AgentEvent) -> None: ...


class NullChannel:
    """Discards everything, so a run with nobody watching costs nothing."""

    async def publish(self, event: AgentEvent) -> None:
        return None
