"""What each model request is made of, on a span around it, so a trace shows where input goes.

Estimated at four characters a token: good for shares between parts, not for billing,
which the provider's own count on the same span covers.
"""

import json
from dataclasses import dataclass

from opentelemetry import trace
from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability, WrapModelRequestHandler
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolReturnPart
from pydantic_ai.models import ModelRequestContext

from mycel.agents.core.deps import MycelDeps


def _tokens(text: str) -> int:
    return len(text) // 4


def measure(context: ModelRequestContext) -> dict[str, int]:
    params = context.model_request_parameters
    instructions = "".join(p.content for p in params.instruction_parts or [])
    tools = json.dumps(
        [[t.name, t.description, t.parameters_json_schema] for t in params.function_tools]
    )
    results = history = 0
    for message in context.messages:
        for part in message.parts:
            size = _tokens(_text(part))
            if isinstance(message, ModelRequest) and isinstance(part, ToolReturnPart):
                results += size
            else:
                history += size
    return {
        "instructions": _tokens(instructions),
        "tools": _tokens(tools),
        "history": history,
        "tool_results": results,
    }


def _text(part: object) -> str:
    content = getattr(part, "content", None) or getattr(part, "args", None) or ""
    return content if isinstance(content, str) else str(content)


_tracer = trace.get_tracer(__name__)


@dataclass
class PromptParts(AbstractCapability[MycelDeps]):
    async def wrap_model_request(
        self,
        ctx: RunContext[MycelDeps],
        *,
        request_context: ModelRequestContext,
        handler: WrapModelRequestHandler,
    ) -> ModelResponse:
        # Wraps the request so the model's own span, with the provider's count, sits inside.
        attributes = {f"mycel.prompt.{k}_tokens": v for k, v in measure(request_context).items()}
        with _tracer.start_as_current_span("prompt parts", attributes=attributes):
            return await handler(request_context)
