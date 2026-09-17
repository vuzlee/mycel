"""Degenerate-loop detection: the one guard pydantic-ai does not provide.

Tested against hand-built message histories rather than a live run, so the ladder
(warn once, then stop) is checked directly without spending a model call.
"""

from typing import Any

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart

from mycel.agents.core.exceptions import DegenerateLoop
from mycel.agents.core.guards import count_identical_calls, fingerprint, guard_repeat


class _Ctx:
    """Stand-in for RunContext — guard_repeat only ever reads `.messages`."""

    def __init__(self, messages: list[Any]) -> None:
        self.messages = messages


def _call(tool: str, **args: Any) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(tool, args)])


class TestFingerprint:
    def test_argument_order_does_not_matter(self) -> None:
        assert fingerprint("t", {"a": 1, "b": 2}) == fingerprint("t", {"b": 2, "a": 1})

    def test_different_arguments_differ(self) -> None:
        assert fingerprint("t", {"a": 1}) != fingerprint("t", {"a": 2})

    def test_different_tools_differ(self) -> None:
        assert fingerprint("x", {"a": 1}) != fingerprint("y", {"a": 1})

    def test_unserialisable_value_does_not_raise(self) -> None:
        """A guard that crashes is worse than a guard that is occasionally coarse."""
        assert fingerprint("t", {"a": object()})


class TestCountIdenticalCalls:
    def test_counts_only_matching_calls(self) -> None:
        history = [
            _call("growth", previous=1, current=2),
            _call("growth", previous=1, current=2),
            _call("growth", previous=9, current=9),
            _call("stats", values=[1]),
        ]
        target = fingerprint("growth", {"previous": 1, "current": 2})
        assert count_identical_calls(history, target) == 2

    def test_ignores_non_response_messages(self) -> None:
        assert count_identical_calls([ModelRequest(parts=[])], fingerprint("t", {})) == 0

    def test_ignores_text_parts(self) -> None:
        history = [ModelResponse(parts=[TextPart("just talking")])]
        assert count_identical_calls(history, fingerprint("t", {})) == 0

    def test_empty_history(self) -> None:
        assert count_identical_calls([], fingerprint("t", {})) == 0


class TestGuardRepeat:
    def test_first_call_passes(self) -> None:
        ctx = _Ctx([])
        guard_repeat(ctx, "growth", previous=1, current=2)  # type: ignore[arg-type]

    def test_different_arguments_never_trip(self) -> None:
        """Calling the same tool with new inputs is the normal case, not a loop."""
        ctx = _Ctx([_call("growth", previous=1, current=2)])
        guard_repeat(ctx, "growth", previous=3, current=4)  # type: ignore[arg-type]

    def test_repeat_at_threshold_asks_the_model_to_stop(self) -> None:
        """First a warning in words — often enough to break the loop on its own."""
        ctx = _Ctx([_call("growth", previous=1, current=2)] * 2)
        with pytest.raises(ModelRetry, match="already called"):
            guard_repeat(ctx, "growth", previous=1, current=2)  # type: ignore[arg-type]

    def test_repeat_after_being_warned_is_a_hard_stop(self) -> None:
        """A bare ModelRetry on every repeat is itself a loop, just a costlier one."""
        ctx = _Ctx([_call("growth", previous=1, current=2)] * 3)
        with pytest.raises(DegenerateLoop) as exc:
            guard_repeat(ctx, "growth", previous=1, current=2)  # type: ignore[arg-type]
        assert exc.value.tool == "growth"
        assert exc.value.count == 3

    def test_threshold_is_configurable(self) -> None:
        ctx = _Ctx([_call("growth", previous=1, current=2)] * 3)
        guard_repeat(ctx, "growth", threshold=5, previous=1, current=2)  # type: ignore[arg-type]

    def test_message_tells_the_model_what_to_do(self) -> None:
        """The retry text is a prompt; it has to be an instruction, not a complaint."""
        ctx = _Ctx([_call("growth", previous=1, current=2)] * 2)
        with pytest.raises(ModelRetry) as exc:
            guard_repeat(ctx, "growth", previous=1, current=2)  # type: ignore[arg-type]
        assert "different tool" in str(exc.value)


class TestNumericCanonicalisation:
    """A tool body sees coerced arguments while the history holds what was sent. If the
    two fingerprint differently the guard never fires at all — silently."""

    def test_int_and_float_fingerprint_the_same(self) -> None:
        assert fingerprint("t", {"n": 100}) == fingerprint("t", {"n": 100.0})

    def test_nesting_is_canonicalised_too(self) -> None:
        assert fingerprint("t", {"v": {"a": 1}}) == fingerprint("t", {"v": {"a": 1.0}})
        assert fingerprint("t", {"v": [1, 2]}) == fingerprint("t", {"v": [1.0, 2.0]})

    def test_bool_is_not_a_number(self) -> None:
        """`True` is an `int` in Python, but a model that sent a boolean did not send 1."""
        assert fingerprint("t", {"flag": True}) != fingerprint("t", {"flag": 1.0})

    def test_different_values_still_differ(self) -> None:
        assert fingerprint("t", {"n": 100}) != fingerprint("t", {"n": 101})
