"""Where a run sends its events."""

from typing import Any, Protocol

from mycel.events.event import TOOL_CALLED, TOOL_RETURNED, AgentEvent, SequencedEvent

#: The only types kept. Reasoning is the longest part of a run and the least useful when
#: read back; a tool call and its result are what make an answer checkable.
_KEPT = frozenset({TOOL_CALLED, TOOL_RETURNED})


class EventChannel(Protocol):
    """A sink for one job's events."""

    async def publish(self, event: AgentEvent) -> None: ...


class NullChannel:
    """Discards everything, so a run with nobody watching costs nothing."""

    async def publish(self, event: AgentEvent) -> None:
        return None


class RecordingChannel:
    """Publishes as usual, and keeps the tool calls so the turn can be reopened later.

    Wraps rather than replaces: the stream is still what a watching page reads, and this
    only remembers a copy of the part worth keeping.

    Wrapping rather than re-reading the stream at the end, because by then the stream may
    be short of exactly what matters. `maxlen` trims from the front, so a long run loses
    its first tool calls first — the ones that set its direction.
    """

    #: Steps one turn keeps. A run past this is a loop, and a loop writes the same call
    #: forever; the head is kept because the first calls are what chose the direction.
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
            # Numbered here rather than taken from the stream: the stream's sequence counts
            # every event, so a kept list carrying it would read as one long gap. These are
            # the steps in order, and a replay has nothing to be told it is missing.
            self._steps.append(
                SequencedEvent(seq=len(self._steps) + 1, **event.model_dump()).model_dump()
            )
        else:
            self._dropped += 1

    @property
    def steps(self) -> list[dict[str, Any]]:
        """What to store. Empty stays empty — a turn that called nothing keeps nothing."""
        return list(self._steps)

    @property
    def dropped(self) -> int:
        """Tool events past the ceiling, so a caller can say so rather than lose them
        silently."""
        return self._dropped
