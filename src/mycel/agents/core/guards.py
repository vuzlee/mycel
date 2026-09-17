"""Stop an agent from burning money on its own.

  runaway      too many loops or too many tool calls in one run — stop
  degenerate   the model repeating itself (same tool, same arguments) — stop
  retry_prompt off-schema output gets a re-prompt naming the exact error, not a blind retry

**Two of those three are now configuration, not code.** pydantic-ai enforces runaway via
`UsageLimits(request_limit=, tool_calls_limit=)`, which `runner.run` builds from
`AgentSettings`, and retry_prompt via `output_type` + `ModelRetry` + `retries=`. Do not go
looking in this file for a loop counter; there isn't one, and that is deliberate.

Only **degenerate** needs real code, because nothing upstream detects it. This file is that.

Different from `llm/budget.py`: budget counts money across a whole job, guards count
behaviour within a single run. A broken loop hits a guard in seconds; by the time it hits
the budget the money is already spent.

Detection is a scan of `ctx.messages`, not a counter carried in deps — stateless, so it
cannot drift out of sync with the real history, and it survives retries for free.
"""

import hashlib
import json
from typing import TYPE_CHECKING, Any

from mycel.agents.core.exceptions import DegenerateLoop

if TYPE_CHECKING:
    from pydantic_ai import RunContext


def _canonical(value: Any) -> Any:
    """Erase differences that are not differences.

    A tool body sees arguments *after* pydantic has coerced them, so a model that sent
    `100` is holding `100.0` by the time `guard_repeat` runs — while the history still
    holds `100`. Left alone the two fingerprints never match and the guard silently never
    fires. Widening every number to float makes the comparison see what the model
    actually did. `bool` is excluded: it is an `int` in Python, but not a number the
    model chose.
    """
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
    """A stable id for one (tool, arguments) pair.

    Sorted keys so argument order does not matter, `default=str` so an unserialisable
    value degrades to its repr instead of raising — a guard that crashes is worse than a
    guard that is occasionally coarse.
    """
    payload = json.dumps(
        {"tool": tool, "args": _canonical(args)}, sort_keys=True, default=str
    )
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


def guard_repeat(
    ctx: "RunContext[Any]", tool: str, threshold: int = 2, **args: Any
) -> None:
    """Call at the top of every tool body, before doing any work.

    The ladder matters. On the first repeat the model is told, in words, what it already
    did — often enough to break the loop. Only a repeat *after* being told is treated as
    stuck, because a bare `ModelRetry` on every repeat is itself a loop, just a more
    expensive one.
    """
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
