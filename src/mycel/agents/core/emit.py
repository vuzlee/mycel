"""Turns the nodes of an agent run into events a client can render."""

from typing import TYPE_CHECKING

from pydantic_ai import messages

from mycel.events.event import AgentEvent

if TYPE_CHECKING:
    from mycel.agents.core.deps import MycelDeps

#: Kept small on purpose. A client ignores types it does not know, so adding one later is
#: safe; removing one is not.
RUN_STARTED = "run_started"
RUN_FINISHED = "run_finished"
TEXT = "text"
THINKING = "thinking"
TOOL_CALLED = "tool_called"
TOOL_RETURNED = "tool_returned"

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

    async def _response(self, response: messages.ModelResponse) -> None:
        for part in response.parts:
            if isinstance(part, messages.TextPart):
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


def _preview(value: object) -> str:
    text = value if isinstance(value, str) else str(value)
    return text[:PREVIEW_CHARS]
