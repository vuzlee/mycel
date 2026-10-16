"""`translate_agent_errors`, the seam where pydantic-ai's failures become Mycel's."""

import httpx2
import pytest
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)

from mycel.agents.core.exceptions import (
    ModelAuth,
    ModelCallFailed,
    ModelNotFound,
    ModelProviderError,
    ModelQuota,
    ModelRejected,
    ModelTimeout,
    ModelUnreachable,
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

    def test_unexpected_behavior_becomes_validation_failure(self) -> None:
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


class TestErrorKinds:
    """Each kind asks the user for a different action, so each is its own class."""

    @pytest.mark.parametrize(
        ("status", "kind"),
        [
            (402, ModelQuota),
            (429, ModelQuota),
            (401, ModelAuth),
            (403, ModelAuth),
            (404, ModelNotFound),
            (500, ModelProviderError),
            (503, ModelProviderError),
        ],
    )
    def test_a_status_maps_to_its_kind(self, status: int, kind: type[ModelCallFailed]) -> None:
        with pytest.raises(kind) as exc:
            _raise(ModelHTTPError(status_code=status, model_name="qwen"))
        assert SPEC in str(exc.value)
        assert str(status) in str(exc.value)

    def test_a_400_about_the_key_is_auth(self) -> None:
        """Google answers a bad key with 400 'Please pass a valid API key'."""
        body = {"error": {"code": 400, "message": "Please pass a valid API key"}}
        with pytest.raises(ModelAuth):
            _raise(ModelHTTPError(status_code=400, model_name="qwen", body=body))

    def test_a_refused_connection_is_unreachable(self) -> None:
        wrapped = ModelAPIError(model_name="qwen", message="connection error")
        wrapped.__cause__ = httpx2.ConnectError("connection refused")
        with pytest.raises(ModelUnreachable):
            _raise(wrapped)

    def test_a_400_is_rejected_and_keeps_the_reason(self) -> None:
        """Gemini 3 refusing a call with no thought signature: retrying sends the same body."""
        body = {"error": {"code": 400, "message": "Function call is missing a thought_signature"}}
        with pytest.raises(ModelRejected) as exc:
            _raise(ModelHTTPError(status_code=400, model_name="gemini", body=body))
        assert "thought_signature" in str(exc.value)

    def test_an_unknown_failure_stays_the_parent(self) -> None:
        with pytest.raises(ModelCallFailed) as exc:
            _raise(ModelHTTPError(status_code=418, model_name="qwen"))
        assert type(exc.value) is ModelCallFailed


class TestTimeoutDetection:
    """pydantic-ai wraps the SDK's own exception."""

    def test_a_wrapped_timeout_is_recognized(self) -> None:
        wrapped = ModelAPIError(model_name="qwen", message="timed out")
        wrapped.__cause__ = httpx2.ReadTimeout("read timed out")

        with pytest.raises(ModelTimeout):
            _raise(wrapped)

    def test_a_wrapped_sdk_timeout_is_recognized(self) -> None:
        """Neither provider SDK inherits from the HTTP library's timeout."""

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
