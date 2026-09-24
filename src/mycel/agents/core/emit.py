"""Turns the nodes of an agent run into events a client can render."""

from collections.abc import AsyncIterable
from typing import TYPE_CHECKING

from pydantic_ai import messages

from mycel.events.event import (
    RUN_FINISHED,
    RUN_STARTED,
    TEXT,
    TEXT_DELTA,
    THINKING,
    TOOL_CALLED,
    TOOL_RETURNED,
    AgentEvent,
)

__all__ = [
    "PREVIEW_CHARS",
    "RUN_FINISHED",
    "RUN_STARTED",
    "TEXT",
    "TEXT_DELTA",
    "THINKING",
    "TOOL_CALLED",
    "TOOL_RETURNED",
    "RunEmitter",
]

if TYPE_CHECKING:
    from mycel.agents.core.deps import MycelDeps

#: Enough to show what a tool was asked and what it said, not enough to leak a whole
#: document into a browser. Raw model output does not go out at all — only `TextPart` and
#: `ThinkingPart`, which are the agent's own prose.
PREVIEW_CHARS = 500


class RunEmitter:
    """Publishes one agent's events, tagged with that agent and its parent tool call."""

    def __init__(self, deps: "MycelDeps", agent: str, parent_tool_call_id: str | None) -> None:
        self._deps = deps
        self._agent = agent
        self._parent = parent_tool_call_id
        self._streamed = False

    async def emit(self, type: str, **payload: object) -> None:
        await self._deps.events.publish(
            AgentEvent(
                agent=self._agent,
                type=type,
                payload=payload,
                parent_tool_call_id=self._parent,
            )
        )

    async def node(self, node: object) -> None:
        """Emit whatever this node of the run is worth showing. Unknown nodes are skipped."""
        response = getattr(node, "model_response", None)
        if response is not None:
            await self._response(response)
            return

        request = getattr(node, "request", None)
        if request is not None:
            await self._request(request)

    async def stream(self, events: "AsyncIterable[object]") -> None:
        """Emit the model's prose as it is written, rather than once the turn is over.

        Sets a flag the finished response then reads: the same words must not go out twice,
        once as deltas and once whole.
        """
        async for event in events:
            delta = _delta(event)
            if delta:
                self._streamed = True
                await self.emit(TEXT_DELTA, text=delta)

    async def _response(self, response: messages.ModelResponse) -> None:
        streamed, self._streamed = self._streamed, False
        for part in response.parts:
            if isinstance(part, messages.TextPart):
                if not streamed:
                    await self.emit(TEXT, text=part.content)
            elif isinstance(part, messages.ThinkingPart):
                # `content` only: `signature` is a provider round-trip token, not prose,
                # and sending it out would leak an opaque credential-ish blob to a browser.
                await self.emit(THINKING, text=part.content)
            elif isinstance(part, messages.ToolCallPart):
                await self.emit(
                    TOOL_CALLED,
                    tool=part.tool_name,
                    tool_call_id=part.tool_call_id,
                    args=_preview(part.args),
                )

    async def _request(self, request: messages.ModelRequest) -> None:
        for part in request.parts:
            if isinstance(part, messages.ToolReturnPart):
                await self.emit(
                    TOOL_RETURNED,
                    tool=part.tool_name,
                    tool_call_id=part.tool_call_id,
                    result=_preview(part.content),
                )


def _delta(event: object) -> str:
    """The text this stream event adds, or "" for events that add none.

    A part starts with whatever the first chunk held and grows by deltas, so both carry
    prose; everything else on the stream is a tool call or a part the run emits whole.
    """
    if isinstance(event, messages.PartStartEvent) and isinstance(event.part, messages.TextPart):
        return event.part.content
    if isinstance(event, messages.PartDeltaEvent) and isinstance(
        event.delta, messages.TextPartDelta
    ):
        return event.delta.content_delta
    return ""


def _preview(value: object) -> str:
    text = value if isinstance(value, str) else str(value)
    return text[:PREVIEW_CHARS]
