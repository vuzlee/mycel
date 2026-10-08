"""Detect a model repeating the same tool call, by scanning the run's message history.

Loop and tool-call limits are `UsageLimits`, built in `runner.run`.
"""

import hashlib
import json
from typing import TYPE_CHECKING, Any

from mycel.agents.core.exceptions import DegenerateLoop

if TYPE_CHECKING:
    from pydantic_ai import RunContext


def _canonical(value: Any) -> Any:
    """Widen ints to float so coerced args (`100.0`) match the history (`100`); bools stay."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def fingerprint(tool: str, args: dict[str, Any]) -> str:
    """A stable hash of one (tool, arguments) pair; unserializable values fall back to str."""
    payload = json.dumps({"tool": tool, "args": _canonical(args)}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def count_identical_calls(messages: "list[Any]", target: str) -> int:
    """How many times `target`'s fingerprint already appears in this run's history."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    seen = 0
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            if not isinstance(part, ToolCallPart):
                continue
            args = part.args_as_dict() if part.args is not None else {}
            if fingerprint(part.tool_name, args) == target:
                seen += 1
    return seen


def guard_repeat(ctx: "RunContext[Any]", tool: str, threshold: int = 2, **args: Any) -> None:
    """Call first in every tool body: warn on the threshold repeat, raise `DegenerateLoop` after."""
    from pydantic_ai import ModelRetry

    calls = count_identical_calls(ctx.messages, fingerprint(tool, args))

    if calls > threshold:
        raise DegenerateLoop(tool, calls)

    if calls == threshold:
        raise ModelRetry(
            f"You already called {tool} with exactly these arguments and have the "
            "result above. Use that result, or call a different tool — calling it "
            "again will return the same answer."
        )
