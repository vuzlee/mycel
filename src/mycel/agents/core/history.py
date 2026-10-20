"""Old tool results cut to their short form before each model request.

The processed list replaces the run's history, so only a result's content changes: its tool
name and the call that asked for it stay, which `guards.guard_repeat` and readers of
`ctx.messages` rely on.
"""

from dataclasses import replace
from typing import Any, Protocol, runtime_checkable

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolReturnPart

#: Rounds whose results stay whole; the model is still working from these.
KEEP_ROUNDS = 2


@runtime_checkable
class Brief(Protocol):
    """A tool result that knows its short form. Others stay whole: a delegate's answer is
    the orchestrator's material, not something to fetch again."""

    def brief(self) -> Any: ...


def shrink_old_results(messages: list[ModelMessage]) -> list[ModelMessage]:
    responses = [i for i, m in enumerate(messages) if isinstance(m, ModelResponse)]
    if len(responses) <= KEEP_ROUNDS:
        return messages
    cutoff = responses[-KEEP_ROUNDS]
    return [
        _shrink(m) if i < cutoff and isinstance(m, ModelRequest) else m
        for i, m in enumerate(messages)
    ]


def _shrink(request: ModelRequest) -> ModelRequest:
    parts = [
        replace(p, content=_short(p)) if isinstance(p, ToolReturnPart) else p for p in request.parts
    ]
    return replace(request, parts=parts)


def _short(part: ToolReturnPart) -> Any:
    content = part.content
    if isinstance(content, list):
        return [c.brief() if isinstance(c, Brief) else c for c in content]
    return content.brief() if isinstance(content, Brief) else content
