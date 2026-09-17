"""Agent framework errors: loop exhausted, output failed validation, tool failed, model
timed out.

Inherits the base exception in `core/`, so layers above can catch by group without knowing
the details.

`translate_agent_errors` is where pydantic-ai's exceptions become Mycel's. Two are
deliberately *not* translated, because they are control flow rather than failure:

  ModelRetry       a tool asking the model to try again — must reach pydantic-ai
  ValidationError  raised inside an output validator — same

Wrapping either breaks the retry machinery and turns a recoverable run into a dead one.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from mycel.core.exceptions import MycelError


class AgentError(MycelError):
    """Base for everything the agent runtime raises."""


class ModelTimeout(AgentError):
    """The model did not answer in time.

    Names the tier, because the answer differs: a cloud timeout is usually transient, a
    local one usually means the vLLM container is down and the whole pipeline is stalled.
    """


class RunawayStopped(AgentError):
    """A run hit its request or tool-call ceiling and was stopped."""


class DegenerateLoop(AgentError):
    """The model called the same tool with the same arguments once too often.

    Distinct from `RunawayStopped`: that is "too much work", this is "no progress". The
    fix is a prompt change, not a higher limit.
    """

    def __init__(self, tool: str, count: int) -> None:
        super().__init__(
            f"tool {tool!r} was called {count} times with identical arguments; "
            "the run made no progress and was stopped"
        )
        self.tool = tool
        self.count = count


class OutputValidationFailed(AgentError):
    """The model could not produce output matching the schema within its retries."""


@contextmanager
def translate_agent_errors(model_spec: str) -> Iterator[None]:
    """Turn pydantic-ai's exceptions into Mycel's, naming which backend was at fault."""
    import httpx2
    from pydantic_ai.exceptions import (
        UnexpectedModelBehavior,
        UsageLimitExceeded,
    )

    try:
        yield
    except UsageLimitExceeded as exc:
        raise RunawayStopped(f"{model_spec}: {exc}") from exc
    except UnexpectedModelBehavior as exc:
        raise OutputValidationFailed(f"{model_spec}: {exc}") from exc
    except httpx2.TimeoutException as exc:
        # Say plainly which side is at fault: a local timeout means the vLLM container is
        # down, and a message that does not say so sends people hunting in the wrong place.
        raise ModelTimeout(f"{model_spec} did not respond in time: {exc}") from exc
