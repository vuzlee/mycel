"""`translate_agent_errors`, the seam where pydantic-ai's failures become Mycel's.

Worth its own file because the translation is invisible until production: a missed case
does not fail a test, it just reaches the operator as a framework exception with no tier
on it.
"""

import httpx2
import pytest
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)

from mycel.agents.core.exceptions import (
    ModelCallFailed,
    ModelTimeout,
    OutputValidationFailed,
    RunawayStopped,
    translate_agent_errors,
)

SPEC = "local:qwen3-4b"


def _raise(exc: BaseException) -> None:
    with translate_agent_errors(SPEC):
        raise exc


class TestTranslation:
    def test_a_usage_limit_becomes_runaway(self) -> None:
        with pytest.raises(RunawayStopped):
            _raise(UsageLimitExceeded("request_limit of 3 exceeded"))

    def test_unexpected_behaviour_becomes_validation_failure(self) -> None:
        with pytest.raises(OutputValidationFailed):
            _raise(UnexpectedModelBehavior("no output"))

    def test_a_provider_failure_becomes_model_call_failed(self) -> None:
        with pytest.raises(ModelCallFailed):
            _raise(ModelAPIError(model_name="qwen", message="bad request"))

    def test_an_http_status_is_a_provider_failure(self) -> None:
        """`ModelHTTPError` subclasses `ModelAPIError`; 429 and 5xx must not leak raw."""
        with pytest.raises(ModelCallFailed):
            _raise(ModelHTTPError(status_code=429, model_name="qwen"))

    def test_every_translation_names_the_backend(self) -> None:
        """The tier is the whole diagnostic value: cloud is transient, local is down."""
        with pytest.raises(ModelCallFailed) as exc:
            _raise(ModelAPIError(model_name="qwen", message="refused"))
        assert SPEC in str(exc.value)


class TestTimeoutDetection:
    """pydantic-ai wraps the SDK's own exception, so a timeout is only visible from the
    `__cause__` chain underneath `ModelAPIError`."""

    def test_a_wrapped_timeout_is_recognised(self) -> None:
        wrapped = ModelAPIError(model_name="qwen", message="timed out")
        wrapped.__cause__ = httpx2.ReadTimeout("read timed out")

        with pytest.raises(ModelTimeout):
            _raise(wrapped)

    def test_a_wrapped_sdk_timeout_is_recognised(self) -> None:
        """Neither provider SDK inherits from the HTTP library's timeout, so the match is
        by name."""

        class APITimeoutError(Exception):
            pass

        wrapped = ModelAPIError(model_name="qwen", message="timed out")
        wrapped.__cause__ = APITimeoutError("request timed out")

        with pytest.raises(ModelTimeout):
            _raise(wrapped)

    def test_a_plain_failure_is_not_a_timeout(self) -> None:
        with pytest.raises(ModelCallFailed):
            _raise(ModelAPIError(model_name="qwen", message="invalid api key"))


class TestControlFlowPassesThrough:
    def test_model_retry_is_not_translated(self) -> None:
        """Wrapping it would break the retry machinery and kill a recoverable run."""
        from pydantic_ai import ModelRetry

        with pytest.raises(ModelRetry):
            _raise(ModelRetry("try again"))
