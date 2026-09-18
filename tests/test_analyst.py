"""The analyst agent, run against fake models.

`TestModel` proves the wiring: every tool signature is serialisable and the output schema
is satisfiable. `FunctionModel` drives the sequences that matter — an uncited figure, a
tool that refuses, a model stuck in a loop.
"""

from decimal import Decimal
from typing import Any

import pytest
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from mycel.agents.agent.analyst import Analysis, Analyst
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.exceptions import DegenerateLoop
from mycel.llm.budget import JobBudget

pytestmark = pytest.mark.anyio

LOCAL = AgentSettings(model_spec="local:qwen3-4b")

# TestModel calls every tool with the same placeholder arguments on every step, which is
# exactly the pattern guards.py exists to stop. Wiring tests therefore disable the guard;
# they are checking that the tools are callable, not that the model is sane.
UNGUARDED = AgentSettings(model_spec="local:qwen3-4b", repeat_threshold=1_000_000)


@pytest.fixture
def deps() -> MycelDeps:
    return MycelDeps(job_id="job-1", budget=JobBudget("job-1", Decimal("1.00")), settings=LOCAL)


@pytest.fixture
def unguarded_deps() -> MycelDeps:
    """The guard reads its threshold from deps, not from the agent, because the limit
    belongs to the run rather than to the agent definition."""
    return MycelDeps(job_id="job-1", budget=JobBudget("job-1", Decimal("1.00")), settings=UNGUARDED)


def _analysis_call(figures: list[dict[str, Any]], findings: list[str]) -> ModelResponse:
    """A model response that produces the final Analysis output."""
    return ModelResponse(
        parts=[
            ToolCallPart("final_result", {"figures": figures, "findings": findings, "caveats": []})
        ]
    )


# Each tool with arguments it will actually accept. TestModel cannot drive these: it
# sends 0.0 for every parameter, and most of these functions are undefined at zero — which
# is the point of their guard clauses, not a flaw in them.
VALID_CALLS: list[tuple[str, dict[str, Any]]] = [
    ("percent_change", {"previous": 100.0, "current": 130.0}),
    ("absolute_change", {"previous": 100.0, "current": 130.0}),
    ("percentage", {"part": 25.0, "whole": 200.0}),
    ("cagr", {"begin": 100.0, "end": 200.0, "periods": 3.0}),
    ("share_of_total", {"values": {"a": 1.0, "b": 3.0}}),
    ("summary_stats", {"values": [1.0, 2.0, 3.0]}),
]


class TestWiring:
    async def test_every_tool_is_registered_and_callable(self, unguarded_deps: MycelDeps) -> None:
        """Walk every tool once, then produce an output.

        This is the smoke test that no tool signature is unserialisable and no compute
        function was left unregistered — an unregistered tool is a capability the analyst
        silently does not have.
        """
        step = [0]

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            i = step[0]
            step[0] += 1
            if i < len(VALID_CALLS):
                name, args = VALID_CALLS[i]
                return ModelResponse(parts=[ToolCallPart(name, args)])
            return _analysis_call(
                [{"label": "growth", "value": 30.0, "source": "percent_change(100, 130)"}],
                ["up 30%"],
            )

        agent = Analyst.build(LOCAL)
        with capture_run_messages() as messages:
            with agent.override(model=FunctionModel(respond)):
                result = await agent.run("Revenue 100 -> 130.", deps=unguarded_deps)

        assert isinstance(result.output, Analysis)
        failed = [
            part
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, RetryPromptPart)
        ]
        assert not failed, f"a tool refused a valid call: {[p.content for p in failed]}"


class TestOutputValidator:
    async def test_uncited_figure_is_rejected_then_accepted(self, deps: MycelDeps) -> None:
        """'Numbers with their sources' is enforced, not requested."""
        calls: list[int] = []

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            calls.append(1)
            if len(calls) == 1:
                return _analysis_call(
                    [{"label": "growth", "value": 30.0, "source": ""}], ["up 30%"]
                )
            return _analysis_call(
                [{"label": "growth", "value": 30.0, "source": "percent_change(100, 130)"}],
                ["up 30%"],
            )

        agent = Analyst.build(LOCAL)
        with capture_run_messages() as messages:
            with agent.override(model=FunctionModel(respond)):
                result = await agent.run("Revenue 100 -> 130.", deps=deps)

        assert result.output.figures[0].source == "percent_change(100, 130)"
        assert len(calls) == 2, "the model should have been re-prompted exactly once"
        retries = [
            part
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, RetryPromptPart)
        ]
        assert retries, "an uncited figure must produce a retry prompt"

    async def test_retry_message_names_the_offending_figure(self, deps: MycelDeps) -> None:
        """A retry prompt that does not say which figure is wrong is a blind retry."""
        seen: list[str] = []

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            for message in messages:
                if isinstance(message, ModelRequest):
                    for part in message.parts:
                        if isinstance(part, RetryPromptPart):
                            seen.append(str(part.content))
            if not seen:
                return _analysis_call(
                    [{"label": "market share", "value": 12.5, "source": ""}], ["12.5%"]
                )
            return _analysis_call(
                [{"label": "market share", "value": 12.5, "source": "percentage(25, 200)"}],
                ["12.5%"],
            )

        agent = Analyst.build(LOCAL)
        with agent.override(model=FunctionModel(respond)):
            await agent.run("Share?", deps=deps)

        assert seen and "market share" in seen[0]

    async def test_cited_figure_passes_first_time(self, deps: MycelDeps) -> None:
        calls: list[int] = []

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            calls.append(1)
            return _analysis_call(
                [{"label": "growth", "value": 30.0, "source": "percent_change"}], ["up"]
            )

        agent = Analyst.build(LOCAL)
        with agent.override(model=FunctionModel(respond)):
            result = await agent.run("Revenue 100 -> 130.", deps=deps)
        assert len(calls) == 1
        assert result.output.figures[0].label == "growth"


class TestToolErrorsBecomeRetries:
    async def test_undefined_calculation_is_re_prompted(self, deps: MycelDeps) -> None:
        """compute.py's messages are written for the model; they must reach it intact."""
        seen: list[str] = []

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            for message in messages:
                if isinstance(message, ModelRequest):
                    for part in message.parts:
                        if isinstance(part, RetryPromptPart):
                            seen.append(str(part.content))
            if not seen:
                # Division by zero: percent_change is undefined from 0.
                return ModelResponse(
                    parts=[ToolCallPart("percent_change", {"previous": 0, "current": 50})]
                )
            return _analysis_call(
                [{"label": "change", "value": 50.0, "source": "absolute_change(0, 50)"}],
                ["up 50 in absolute terms"],
            )

        agent = Analyst.build(LOCAL)
        with agent.override(model=FunctionModel(respond)):
            result = await agent.run("From 0 to 50?", deps=deps)

        assert seen, "a refused tool call must produce a retry prompt"
        assert "absolute change" in seen[0], "the message must say what to do instead"
        assert result.output.figures[0].value == 50.0


class TestDegenerateLoop:
    async def test_repeating_the_same_call_is_stopped(self, deps: MycelDeps) -> None:
        """A model that keeps asking the same question never reaches an output, so the
        output validator cannot catch it. This is why guards.py exists."""

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(
                parts=[ToolCallPart("percent_change", {"previous": 100, "current": 130})]
            )

        agent = Analyst.build(LOCAL)
        with pytest.raises(DegenerateLoop) as exc:
            with agent.override(model=FunctionModel(respond)):
                await agent.run("Revenue 100 -> 130.", deps=deps)
        assert exc.value.tool == "percent_change"

    async def test_varying_arguments_are_not_a_loop(self, deps: MycelDeps) -> None:
        """Calling one tool repeatedly with new inputs is normal work."""
        step = [0]

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            step[0] += 1
            if step[0] <= 3:
                return ModelResponse(
                    parts=[
                        ToolCallPart("percent_change", {"previous": 100, "current": 100 + step[0]})
                    ]
                )
            return _analysis_call(
                [{"label": "growth", "value": 3.0, "source": "percent_change"}], ["up"]
            )

        agent = Analyst.build(LOCAL)
        with agent.override(model=FunctionModel(respond)):
            result = await agent.run("Revenue?", deps=deps)
        assert result.output.findings == ["up"]
