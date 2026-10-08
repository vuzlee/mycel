"""Agent runtime errors, and the translation from pydantic-ai's exceptions.

`ModelRetry` and output `ValidationError` are never translated: they drive pydantic-ai retries.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from mycel.core.exceptions import MycelError


class AgentError(MycelError):
    """Base for everything the agent runtime raises."""


class TransportError(AgentError):
    """The provider could not be reached or did not answer: retry the job, do not narrate it."""


class ModelTimeout(TransportError):
    """The model did not answer in time."""


class RunawayStopped(AgentError):
    """A run hit its request or tool-call ceiling and was stopped."""


class DegenerateLoop(AgentError):
    """The model repeated an identical tool call: no progress, unlike `RunawayStopped`."""

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
    """A tool's environment failed (quota, outage); unlike `ModelRetry`, retrying cannot help."""

    def __init__(self, tool: str, reason: str) -> None:
        super().__init__(f"tool {tool!r} failed: {reason}")
        self.tool = tool
        self.reason = reason


class ModelCallFailed(TransportError):
    """The provider rejected the request or was unreachable."""


def _all_models_failed(model_spec: str, group: BaseException) -> TransportError:
    """One error for a failed fallback chain; a timeout only if every model timed out."""
    causes = list(getattr(group, "exceptions", ()))
    said = "; ".join(str(cause) for cause in causes) or str(group)
    detail = f"{model_spec} and its fallbacks all failed: {said}"
    if causes and all(caused_by_timeout(cause) for cause in causes):
        return ModelTimeout(detail)
    return ModelCallFailed(detail)


def caused_by_timeout(exc: BaseException) -> bool:
    """Whether a timeout is anywhere in the cause chain, matched by type or by SDK class name."""
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
        # Not a `ModelAPIError`, so it would otherwise skip the transport clause below.
        raise _all_models_failed(model_spec, exc) from exc
    except UsageLimitExceeded as exc:
        raise RunawayStopped(f"{model_spec}: {exc}") from exc
    except UnexpectedModelBehavior as exc:
        raise OutputValidationFailed(f"{model_spec}: {exc}") from exc
    except ModelAPIError as exc:
        if caused_by_timeout(exc):
            raise ModelTimeout(f"{model_spec} did not respond in time: {exc}") from exc
        raise ModelCallFailed(f"{model_spec}: {exc}") from exc
