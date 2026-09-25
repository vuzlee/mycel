"""Agent framework errors: loop exhausted, output failed validation, tool failed, model
timed out.

Inherits the base exception in `core/`, so layers above can catch by group without knowing
the details.

`translate_agent_errors` is where pydantic-ai's exceptions become Mycel's. Two are
deliberately *not* translated, because they are control flow rather than failure:

  ModelRetry       a tool asking the model to try again — must reach pydantic-ai
  ValidationError  raised inside an output validator — same

Wrapping either breaks the retry machinery and turns a recoverable run into a dead one.

Provider failures arrive as `ModelAPIError`: pydantic-ai catches the SDK's own exception
and re-raises, so a timeout is only recognisable from the `__cause__` chain underneath.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from mycel.core.exceptions import MycelError


class AgentError(MycelError):
    """Base for everything the agent runtime raises."""


class TransportError(AgentError):
    """The provider could not be reached, or would not answer. Not a result.

    The distinction this draws is the one `tools/delegate.py` splits on. Every other
    `AgentError` is something that happened *during* a run and will happen again the same
    way: a tool with no data, a schema the model could not fill, a loop making no progress.
    Those are answers, poor ones, and an agent narrating them is right.

    This is not an answer. The request never reached a model, or the model never replied,
    and the only thing that changes the outcome is trying again later — which is exactly
    what `queue/retry.py` exists to do. Narrating it produces a job marked done whose text
    has to be *read* to discover it says nothing.

    A parent class rather than a tuple of names at each `except`, so a third kind of
    transport failure lands on the right side of the line without an edit anywhere.
    """


class ModelTimeout(TransportError):
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


class ToolFailed(AgentError):
    """A tool could not do its work, and no amount of re-prompting would change that.

    The counterpart to `ModelRetry`, and the distinction is the whole point: a tool whose
    *arguments* were wrong raises `ModelRetry` so the model can fix them, while a tool whose
    *world* is wrong — quota spent, search API down, Qdrant unreachable — raises this. Ask
    the model to retry that and it walks the same loop until `max_retries` turns a plain
    outage into an unreadable run error.

    Names the tool, because by the time this surfaces the caller sees a failed job and not
    which capability was missing.
    """

    def __init__(self, tool: str, reason: str) -> None:
        super().__init__(f"tool {tool!r} failed: {reason}")
        self.tool = tool
        self.reason = reason


class ModelCallFailed(TransportError):
    """The provider rejected the request or was unreachable."""


def _all_models_failed(model_spec: str, group: BaseException) -> TransportError:
    """One Mycel error for a whole failed chain, naming what each model said.

    A timeout only if *every* model timed out: one model that answered with a 503 makes
    "did not respond in time" a wrong sentence, and the difference decides where the
    reader goes looking.
    """
    causes = list(getattr(group, "exceptions", ()))
    said = "; ".join(str(cause) for cause in causes) or str(group)
    detail = f"{model_spec} and its fallbacks all failed: {said}"
    if causes and all(caused_by_timeout(cause) for cause in causes):
        return ModelTimeout(detail)
    return ModelCallFailed(detail)


def caused_by_timeout(exc: BaseException) -> bool:
    """Whether a timeout is anywhere under `exc`.

    Public because `model_builder.py` asks the same question for a different reason: here
    it decides which Mycel error to raise, there whether to try the next model.

    Provider SDKs do not share a base class and none of them inherit from the HTTP
    library's timeout, so this matches on the chain by name as well as by type.
    """
    import httpx2

    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, (httpx2.TimeoutException, TimeoutError)):
            return True
        if type(seen).__name__ == "APITimeoutError":
            return True
        seen = seen.__cause__ or seen.__context__
    return False


@contextmanager
def translate_agent_errors(model_spec: str) -> Iterator[None]:
    """Turn pydantic-ai's exceptions into Mycel's, naming which backend was at fault."""
    from pydantic_ai.exceptions import (
        FallbackExceptionGroup,
        ModelAPIError,
        UnexpectedModelBehavior,
        UsageLimitExceeded,
    )

    try:
        yield
    except FallbackExceptionGroup as exc:
        # Every model in the chain failed. This arrives as a group rather than as a
        # `ModelAPIError`, so without this clause it would sail past the one below and
        # reach `tools/delegate.py` as an ordinary exception — the exact shape batch 054
        # closed, where nothing was reached and the job was written up as an answer.
        raise _all_models_failed(model_spec, exc) from exc
    except UsageLimitExceeded as exc:
        raise RunawayStopped(f"{model_spec}: {exc}") from exc
    except UnexpectedModelBehavior as exc:
        raise OutputValidationFailed(f"{model_spec}: {exc}") from exc
    except ModelAPIError as exc:
        # Which side failed decides where to look: a local timeout means the vLLM
        # container is down, a cloud one is usually transient.
        if caused_by_timeout(exc):
            raise ModelTimeout(f"{model_spec} did not respond in time: {exc}") from exc
        raise ModelCallFailed(f"{model_spec}: {exc}") from exc
