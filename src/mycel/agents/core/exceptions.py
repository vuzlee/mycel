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


class ModelQuota(ModelCallFailed):
    """429 or 402: out of quota, rate limited after the gateway's retries, or out of credit."""


class ModelAuth(ModelCallFailed):
    """401 or 403: the key was rejected."""


class ModelNotFound(ModelCallFailed):
    """404: the endpoint does not serve this model id."""


class ModelUnreachable(ModelCallFailed):
    """No answer at the network level: connection refused, DNS or TLS failure."""


class ModelBlocked(ModelCallFailed):
    """An own model's base URL now points somewhere a call must not go."""


class ModelProviderError(ModelCallFailed):
    """A 5xx from the provider or the gateway, after the gateway's own retries."""


#: HTTP status → (error class, what the user reads).
_BY_STATUS: dict[int, tuple[type[ModelCallFailed], str]] = {
    402: (ModelQuota, "out of credit"),
    429: (ModelQuota, "out of quota or rate limited"),
    401: (ModelAuth, "API key rejected"),
    403: (ModelAuth, "API key not allowed to use this model"),
    404: (ModelNotFound, "model not found at this endpoint"),
}


#: Words a 400 uses when it is about the key: Google answers a bad key with 400, not 401.
_KEY_WORDS = ("api key", "api_key", "apikey")


def key_rejected(status: int, body: object) -> bool:
    """A 400 whose body is about the key, which is an auth failure in all but its status."""
    return status == 400 and any(w in str(body).lower() for w in _KEY_WORDS)


def _by_kind(model_spec: str, exc: BaseException) -> ModelCallFailed:
    """The `ModelCallFailed` subclass that says what went wrong, by status or cause."""
    from pydantic_ai.exceptions import ModelHTTPError

    if isinstance(exc, ModelHTTPError):
        status = exc.status_code
        if key_rejected(status, exc.body):
            return ModelAuth(f"{model_spec}: API key rejected (HTTP {status})")
        if status in _BY_STATUS:
            cls, said = _BY_STATUS[status]
            return cls(f"{model_spec}: {said} (HTTP {status})")
        if status >= 500:
            return ModelProviderError(f"{model_spec}: provider error (HTTP {status}): {exc}")
    if _caused_by_connection(exc):
        return ModelUnreachable(f"{model_spec}: cannot reach the model endpoint: {exc}")
    return ModelCallFailed(f"{model_spec}: {exc}")


def _caused_by_connection(exc: BaseException) -> bool:
    """Whether a connect, DNS or TLS failure is anywhere in the cause chain."""
    import httpx2

    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, (httpx2.ConnectError, ConnectionError)):
            return True
        if type(seen).__name__ in ("APIConnectionError", "ConnectError"):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


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
        ModelAPIError,
        UnexpectedModelBehavior,
        UsageLimitExceeded,
    )

    try:
        yield
    except UsageLimitExceeded as exc:
        raise RunawayStopped(f"{model_spec}: {exc}") from exc
    except UnexpectedModelBehavior as exc:
        raise OutputValidationFailed(f"{model_spec}: {exc}") from exc
    except ModelAPIError as exc:
        if caused_by_timeout(exc):
            raise ModelTimeout(f"{model_spec} did not respond in time: {exc}") from exc
        raise _by_kind(model_spec, exc) from exc
