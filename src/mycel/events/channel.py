"""Where a run sends its events."""

from typing import Any, Protocol

from mycel.events.event import TOOL_CALLED, TOOL_RETURNED, AgentEvent, SequencedEvent

#: Only tool calls and results are kept; they make an answer checkable.
_KEPT = frozenset({TOOL_CALLED, TOOL_RETURNED})


class EventChannel(Protocol):
    """A sink for one job's events."""

    async def publish(self, event: AgentEvent) -> None: ...


class NullChannel:
    """Discards everything, so a run with nobody watching costs nothing."""

    async def publish(self, event: AgentEvent) -> None:
        return None


class RecordingChannel:
    """Publishes as usual and keeps the tool calls, since the stream trims from the front."""

    #: Steps one turn keeps; the head is kept because the first calls set the direction.
    MAX_STEPS = 400

    def __init__(self, inner: EventChannel) -> None:
        self._inner = inner
        self._steps: list[dict[str, Any]] = []
        self._dropped = 0

    async def publish(self, event: AgentEvent) -> None:
        await self._inner.publish(event)
        if event.type not in _KEPT:
            return
        if len(self._steps) < self.MAX_STEPS:
            # Renumbered: the stream's sequence counts every event and would show gaps.
            self._steps.append(
                SequencedEvent(seq=len(self._steps) + 1, **event.model_dump()).model_dump()
            )
        else:
            self._dropped += 1

    @property
    def steps(self) -> list[dict[str, Any]]:
        """Steps to store; empty when the turn called no tools."""
        return list(self._steps)

    @property
    def dropped(self) -> int:
        """Tool events past the ceiling, so a caller can report them."""
        return self._dropped
