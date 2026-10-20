"""Past 75% of the token cap the run's middle becomes one summary; under it nothing changes."""

from decimal import Decimal
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage

from mycel.agents.core.compact import compact
from mycel.agents.core.config import AgentSettings
from mycel.agents.core.deps import MycelDeps
from mycel.llm.budget import JobBudget

pytestmark = pytest.mark.anyio

CAP = 1000


def _summarise(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[TextPart("found https://x/0 and https://x/1")])


class _Ctx:
    def __init__(self, spent: int) -> None:
        self.deps = MycelDeps(
            job_id="job-1",
            budget=JobBudget("job-1", Decimal("1.00")),
            settings=AgentSettings(model_spec="local:qwen3-4b", total_tokens_limit=CAP),
        )
        self.usage = RunUsage(input_tokens=spent)
        self.model = FunctionModel(_summarise)


def _history(rounds: int) -> list[ModelMessage]:
    out: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("3 AI news today")])]
    for i in range(rounds):
        out.append(ModelResponse(parts=[ToolCallPart("web_search", {"query": f"q{i}"}, f"c{i}")]))
        out.append(ModelRequest(parts=[ToolReturnPart("web_search", "page " * 200, f"c{i}")]))
    return out


def _text(message: ModelMessage) -> str:
    return " ".join(str(getattr(p, "content", "")) for p in message.parts)


async def test_under_the_threshold_nothing_changes() -> None:
    history = _history(5)
    assert await compact(_Ctx(spent=700), history) == history  # type: ignore[arg-type]


async def test_past_the_threshold_the_middle_becomes_a_summary() -> None:
    history = _history(5)
    out = await compact(_Ctx(spent=800), history)  # type: ignore[arg-type]
    assert out[0] == history[0]
    assert "https://x/1" in _text(out[1])
    assert out[2:] == history[-4:]


async def test_the_summary_call_is_counted() -> None:
    ctx = _Ctx(spent=800)
    await compact(ctx, _history(5))  # type: ignore[arg-type]
    assert ctx.usage.requests == 1


async def test_a_short_run_is_left_alone() -> None:
    history = _history(2)
    assert await compact(_Ctx(spent=900), history) == history  # type: ignore[arg-type]


async def test_no_cap_means_no_compaction() -> None:
    ctx: Any = _Ctx(spent=10_000)
    ctx.deps.settings = AgentSettings(model_spec="local:qwen3-4b")
    history = _history(5)
    assert await compact(ctx, history) == history
