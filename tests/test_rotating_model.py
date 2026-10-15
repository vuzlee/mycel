"""An own model's keys hand over to the next on quota or auth, and only then."""

from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from mycel.agents.core.rotating import RotatingModel

pytestmark = pytest.mark.anyio


def _key(status: int | None, said: list[str], name: str) -> FunctionModel:
    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        said.append(name)
        if status is not None:
            raise ModelHTTPError(status_code=status, model_name=name, body="quota exceeded")
        return ModelResponse(parts=[TextPart(f"from {name}")])

    return FunctionModel(answer)


async def _run(*statuses: int | None) -> tuple[str, list[str], list[tuple[int, int]]]:
    said: list[str] = []
    failed: list[tuple[int, int]] = []

    async def on_failure(position: int, status: int, error: str) -> None:
        failed.append((position, status))

    keyed: list[tuple[int, Any]] = [(i, _key(s, said, f"k{i}")) for i, s in enumerate(statuses)]
    result = await Agent(RotatingModel(keyed, on_failure)).run("q")
    return result.output, said, failed


async def test_the_first_good_key_answers() -> None:
    assert await _run(None, None) == ("from k0", ["k0"], [])


@pytest.mark.parametrize("status", [429, 402, 401, 403])
async def test_quota_or_auth_moves_to_the_next_key(status: int) -> None:
    output, said, failed = await _run(status, None)
    assert output == "from k1"
    assert said == ["k0", "k1"] and failed == [(0, status)]


@pytest.mark.parametrize("status", [400, 404, 500])
async def test_any_other_failure_is_the_models_own(status: int) -> None:
    """Another key of the same model would fail the same way; nothing is set aside."""
    with pytest.raises(ModelHTTPError) as raised:
        await _run(status, None)
    assert raised.value.status_code == status


async def test_every_key_spent_raises_the_last_failure() -> None:
    with pytest.raises(ModelHTTPError) as raised:
        await _run(429, 429, 401)
    assert raised.value.status_code == 401


async def test_a_400_about_the_key_moves_on() -> None:
    said: list[str] = []

    def bad_key(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        said.append("k0")
        raise ModelHTTPError(status_code=400, model_name="k0", body="Please pass a valid API key")

    async def keep(position: int, status: int, error: str) -> None:
        pass

    keyed: list[tuple[int, Any]] = [(0, FunctionModel(bad_key)), (1, _key(None, said, "k1"))]
    result = await Agent(RotatingModel(keyed, keep)).run("q")
    assert result.output == "from k1" and said == ["k0", "k1"]
