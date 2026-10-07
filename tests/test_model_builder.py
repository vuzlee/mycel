"""One client for every model: OpenAI Chat Completions to the LiteLLM gateway.

Which provider answers a `model_name` is `config/litellm/config.yaml`'s business; these
tests pin what the app sends, how a chain is built, and when it moves to the next model.
"""

import pytest
from pydantic_ai.exceptions import FallbackExceptionGroup, ModelAPIError, ModelHTTPError
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.exceptions import (
    ModelCallFailed,
    ModelTimeout,
    TransportError,
    translate_agent_errors,
)
from mycel.agents.core.model_builder import _is_unavailable, build_model
from mycel.core.config import Settings
from mycel.core.exceptions import ConfigError


def _settings(**kwargs: object) -> Settings:
    return Settings(**kwargs)  # type: ignore[arg-type]


class TestOneClient:
    @pytest.mark.parametrize(
        "spec", ["cloud:claude-sonnet-5", "cloud:gemini-3.6-flash", "local:qwen3-4b"]
    )
    def test_every_spec_is_an_openai_chat_model(self, spec: str) -> None:
        model = build_model(spec, settings=_settings())
        assert isinstance(model, OpenAIChatModel)

    def test_the_name_is_the_gateway_model_name(self) -> None:
        """No alias table in code: the name in the spec is the name the gateway serves."""
        model = build_model("cloud:claude-sonnet-5", settings=_settings())
        assert model.model_name == "claude-sonnet-5"

    def test_it_talks_to_the_configured_gateway(self) -> None:
        model = build_model(
            "cloud:claude-sonnet-5", settings=_settings(litellm_base_url="http://litellm:4000")
        )
        assert "litellm:4000" in str(model.base_url)

    def test_the_gateway_key_is_sent(self) -> None:
        model = build_model(
            "cloud:claude-sonnet-5", settings=_settings(litellm_api_key="sk-gateway")
        )
        assert model.client.api_key == "sk-gateway"

    def test_no_gateway_is_a_config_error(self) -> None:
        with pytest.raises(ConfigError, match="litellm_base_url"):
            build_model("cloud:claude-sonnet-5", settings=_settings(litellm_base_url=""))

    def test_a_bad_spec_raises_before_any_call(self) -> None:
        with pytest.raises(ConfigError):
            build_model("gpu:qwen3-4b", settings=_settings())


class TestModelSettings:
    def test_temperature_and_timeout_are_applied(self) -> None:
        """Sent for every model; the gateway drops it where a model rejects it."""
        cfg = AgentSettings(temperature=0.7, timeout_s=5.0)
        model = build_model("cloud:gemini-3.6-flash", agent_settings=cfg, settings=_settings())
        assert model.settings is not None
        assert model.settings["temperature"] == 0.7
        assert model.settings["timeout"] == 5.0

    def test_max_tokens_is_omitted_when_unset(self) -> None:
        model = build_model("cloud:claude-sonnet-5", settings=_settings())
        assert model.settings is not None
        assert "max_tokens" not in model.settings

    def test_the_client_carries_the_retries(self) -> None:
        model = build_model(
            "cloud:claude-sonnet-5",
            agent_settings=AgentSettings(transient_retries=4),
            settings=_settings(),
        )
        assert model.client.max_retries == 4


class TestFallbackChain:
    def test_no_fallbacks_is_one_plain_model(self) -> None:
        assert isinstance(
            build_model("cloud:claude-sonnet-5", settings=_settings()), OpenAIChatModel
        )

    def test_the_chain_is_built_in_the_order_it_was_written(self) -> None:
        model = build_model(
            "cloud:claude-sonnet-5",
            AgentSettings(fallback_specs=("cloud:gemini-3.5-flash-lite", "cloud:gemini-3.6-flash")),
            settings=_settings(),
        )
        assert isinstance(model, FallbackModel)
        assert [inner.model_name for inner in model.models] == [
            "claude-sonnet-5",
            "gemini-3.5-flash-lite",
            "gemini-3.6-flash",
        ]

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_unavailable_moves_to_the_next_model(self, status: int) -> None:
        """429 included: the gateway has already tried every key it holds for this model."""
        assert _is_unavailable(ModelHTTPError(model_name="m", status_code=status, body=None))

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    def test_our_own_bad_request_does_not(self, status: int) -> None:
        assert not _is_unavailable(ModelHTTPError(model_name="m", status_code=status, body=None))

    def test_a_timeout_moves_to_the_next_model(self) -> None:
        assert _is_unavailable(ModelAPIError("m", "timed out")) is False
        timed_out = ModelAPIError("m", "timed out")
        timed_out.__cause__ = TimeoutError()
        assert _is_unavailable(timed_out)


class TestWhenTheWholeChainFails:
    """`FallbackModel` raises a `FallbackExceptionGroup`, which is not a `ModelAPIError`.

    Left untranslated it would walk straight past the model-error clause and arrive at
    `tools/delegate.py` as an ordinary exception — narrated as prose, billed, marked done.
    That is the model-error failure, re-opened by a different exception class.
    """

    def test_it_becomes_a_transport_error_so_the_job_is_retried(self) -> None:
        group = FallbackExceptionGroup(
            "All models from FallbackModel failed",
            [ModelHTTPError(model_name="a", status_code=503, body=None)],
        )
        with pytest.raises(TransportError) as raised:
            with translate_agent_errors("cloud:gemini-3.5-flash-lite"):
                raise group
        assert "cloud:gemini-3.5-flash-lite" in str(raised.value)

    def test_it_says_what_each_model_answered(self) -> None:
        """One sentence per model. Which one was down and which was merely slow is the
        first thing anyone reading the failure wants."""
        group = FallbackExceptionGroup(
            "All models from FallbackModel failed",
            [
                ModelHTTPError(model_name="a", status_code=503, body="overloaded"),
                ModelHTTPError(model_name="b", status_code=504, body="gateway"),
            ],
        )
        with pytest.raises(TransportError) as raised:
            with translate_agent_errors("spec"):
                raise group
        assert "503" in str(raised.value)
        assert "504" in str(raised.value)

    def test_all_of_them_timing_out_is_a_timeout(self) -> None:
        timed_out = ModelAPIError("a", "no answer")
        timed_out.__cause__ = TimeoutError()
        with pytest.raises(ModelTimeout):
            with translate_agent_errors("spec"):
                raise FallbackExceptionGroup("failed", [timed_out])

    def test_one_of_them_answering_503_is_not_a_timeout(self) -> None:
        """ "did not respond in time" is the wrong sentence when a model answered; it sends
        the reader looking at the network instead of at the provider's status page."""
        timed_out = ModelAPIError("a", "no answer")
        timed_out.__cause__ = TimeoutError()
        with pytest.raises(ModelCallFailed):
            with translate_agent_errors("spec"):
                raise FallbackExceptionGroup(
                    "failed",
                    [timed_out, ModelHTTPError(model_name="b", status_code=503, body=None)],
                )
