"""Each model request's input is split into instructions, tools, history and tool results."""

from pydantic_ai.messages import (
    InstructionPart,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext, ModelRequestParameters
from pydantic_ai.tools import ToolDefinition

from mycel.agents.core.prompt_parts import measure


def test_each_part_is_counted_on_its_own() -> None:
    context = ModelRequestContext(
        model=None,  # type: ignore[arg-type]
        messages=[
            ModelRequest(parts=[UserPromptPart("q" * 40)]),
            ModelResponse(parts=[ToolCallPart("web_search", "{}", "c1")]),
            ModelRequest(parts=[ToolReturnPart("web_search", "p" * 4000, "c1")]),
        ],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(
            function_tools=[ToolDefinition(name="web_search", description="d" * 400)],
            instruction_parts=[InstructionPart(content="i" * 800)],
        ),
    )
    parts = measure(context)
    assert parts["instructions"] == 200
    assert parts["tool_results"] == 1000
    assert parts["history"] < 20
    assert parts["tools"] > 100
