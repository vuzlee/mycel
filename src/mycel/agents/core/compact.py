"""A run near its token cap summarises its middle and carries on, instead of failing.

The summary replaces everything between the opening request and the last rounds, so each
later request resends the summary, not the pages it was written from.
"""

from pydantic_ai import RunContext
from pydantic_ai.direct import model_request
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, UserPromptPart
from pydantic_ai.models import Model

from mycel.agents.core.deps import MycelDeps
from mycel.agents.core.history import KEEP_ROUNDS
from mycel.core.logging import get_logger

log = get_logger(__name__)

#: Share of the turn's token cap past which the run compacts.
THRESHOLD = 0.75

_ASK = (
    "Summarise the work above for yourself to continue from: the task, what each search or "
    "call found with its urls, and what is still missing. Facts and urls only, no advice."
)


async def compact(ctx: RunContext[MycelDeps], messages: list[ModelMessage]) -> list[ModelMessage]:
    cap = ctx.deps.settings.total_tokens_limit
    if cap is None or ctx.usage.total_tokens < cap * THRESHOLD:
        return messages
    middle = _middle(messages)
    if middle is None:
        return messages
    start, end = middle
    asked = [*messages[:end], ModelRequest(parts=[UserPromptPart(_ASK)])]
    assert isinstance(ctx.model, Model)
    response = await model_request(ctx.model, asked)
    ctx.usage.incr(response.usage)
    ctx.usage.requests += 1
    log.info(
        "run compacted",
        extra={
            "job_id": ctx.deps.job_id,
            "messages": end - start,
            "tokens": ctx.usage.total_tokens,
        },
    )
    summary = ModelRequest(parts=[UserPromptPart(f"Summary of the work so far:\n{response.text}")])
    return [*messages[:start], summary, *messages[end:]]


def _middle(messages: list[ModelMessage]) -> tuple[int, int] | None:
    """`[start, end)`: after the opening request, before the last rounds; `None` if too short.

    `end` lands on a response, so a tool call is never split from its result.
    """
    responses = [i for i, m in enumerate(messages) if isinstance(m, ModelResponse)]
    if len(responses) <= KEEP_ROUNDS:
        return None
    return 1, responses[-KEEP_ROUNDS]
