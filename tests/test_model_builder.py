"""Spec strings become real provider clients, with the right endpoint and credentials.

Every assertion is on the constructed object. Nothing here sends a request — `conftest.py`
sets `ALLOW_MODEL_REQUESTS = False`, and building a model must not need the network anyway.
"""

import pytest
from pydantic import SecretStr
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.model_builder import build_model
from mycel.core.config import Settings
from mycel.core.exceptions import ConfigError


def _settings(**kwargs: object) -> Settings:
    return Settings(**kwargs)  # type: ignore[arg-type]


class TestCloudTier:
    def test_builds_an_anthropic_model(self) -> None:
        model = build_model(
            "cloud:claude-sonnet-5",
            settings=_settings(anthropic_api_key=SecretStr("sk-test")),
        )
        assert isinstance(model, AnthropicModel)
        assert model.model_name == "claude-sonnet-5"

    def test_missing_key_fails_at_build_time(self) -> None:
        """At startup, not on the first call — a misconfigured deploy must not look
        healthy until someone asks it a question."""
        with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
            build_model("cloud:claude-sonnet-5", settings=_settings())

    def test_error_names_the_spec(self) -> None:
        with pytest.raises(ConfigError, match="cloud:claude-sonnet-5"):
            build_model("cloud:claude-sonnet-5", settings=_settings())

    def test_gemini_gets_googles_own_client(self) -> None:
        """Not the OpenAI-compatible endpoint: that one drops Gemini 3's thought
        signatures, and the API then rejects every run that calls a tool."""
        model = build_model(
            "cloud:gemini-3-flash-preview",
            settings=_settings(gemini_api_key=SecretStr("gk-test")),
        )
        assert isinstance(model, GoogleModel)
        assert model.model_name == "gemini-3-flash-preview"

    def test_gemini_needs_its_own_key(self) -> None:
        with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
            build_model(
                "cloud:gemini-3-flash-preview",
                settings=_settings(anthropic_api_key=SecretStr("sk-test")),
            )

    def test_an_unknown_cloud_model_lists_the_known_ones(self) -> None:
        """The spec usually comes from a YAML file, where a typo is otherwise invisible
        until the first call."""
        with pytest.raises(ConfigError, match="claude-sonnet-5"):
            build_model("cloud:gemini-9-ultra", settings=_settings())

    def test_a_dated_version_stays_out_of_the_spec(self) -> None:
        """Specs are human-sized; pinning a dated release is an edit in one table."""
        model = build_model(
            "cloud:claude-haiku-4-5",
            settings=_settings(anthropic_api_key=SecretStr("sk-test")),
        )
        assert model.model_name == "claude-haiku-4-5-20251001"


class TestLocalTier:
    def test_builds_an_openai_chat_model(self) -> None:
        """vLLM speaks /v1/chat/completions, so the chat model, not the responses one."""
        model = build_model("local:qwen3-4b", settings=_settings())
        assert isinstance(model, OpenAIChatModel)

    def test_needs_no_credential(self) -> None:
        """A local-only deployment must run with no cloud key present at all."""
        assert build_model("local:qwen3-4b", settings=_settings()) is not None

    def test_alias_maps_to_the_served_model(self) -> None:
        """The compose file serves a long HuggingFace name; specs stay human-sized."""
        model = build_model("local:qwen3-4b", settings=_settings())
        assert model.model_name == "Qwen/Qwen2.5-3B-Instruct-AWQ"

    def test_unaliased_name_passes_through(self) -> None:
        model = build_model("local:some-other-model", settings=_settings())
        assert model.model_name == "some-other-model"

    def test_uses_the_configured_base_url(self) -> None:
        model = build_model(
            "local:qwen3-4b",
            settings=_settings(local_llm_base_url="http://vllm:8000/v1"),
        )
        assert "vllm:8000" in str(model.base_url)


class TestModelSettings:
    def test_temperature_and_timeout_are_applied(self) -> None:
        cfg = AgentSettings(temperature=0.7, timeout_s=5.0)
        model = build_model("local:qwen3-4b", agent_settings=cfg, settings=_settings())
        assert model.settings is not None
        assert model.settings["temperature"] == 0.7
        assert model.settings["timeout"] == 5.0

    def test_max_tokens_is_omitted_when_unset(self) -> None:
        """An explicit None would override the provider default with nothing."""
        model = build_model("local:qwen3-4b", settings=_settings())
        assert model.settings is not None
        assert "max_tokens" not in model.settings

    def test_defaults_to_temperature_zero(self) -> None:
        """These agents report figures; a report that changes between identical runs
        cannot be reviewed."""
        model = build_model("local:qwen3-4b", settings=_settings())
        assert model.settings is not None
        assert model.settings["temperature"] == 0.0

    def test_gemini_3_gets_no_sampling_parameters(self) -> None:
        """Gemini 3 rejects temperature rather than ignoring it, so a value configured for
        a model that has no such knob must be dropped, not forwarded."""
        model = build_model(
            "cloud:gemini-3-flash-preview",
            agent_settings=AgentSettings(temperature=0.7),
            settings=_settings(gemini_api_key=SecretStr("gk-test")),
        )
        assert model.settings is not None
        assert "temperature" not in model.settings
        assert model.settings["timeout"] == 60.0


class TestTransientRetries:
    """Each SDK retries the one failed HTTP request itself, so a 503 from an overloaded
    model does not end the run. Asserted on the client, because that is where the setting
    has to land for the SDK to act on it."""

    def test_google_gets_attempts_including_the_first(self) -> None:
        """google-genai counts the original request in `attempts`; the other two SDKs
        count retries after it. Off by one here means one fewer retry than configured."""
        model = build_model(
            "cloud:gemini-3-flash-preview",
            agent_settings=AgentSettings(transient_retries=2, retry_max_delay_s=20.0),
            settings=_settings(gemini_api_key=SecretStr("gk-test")),
        )
        options = model.client._api_client._http_options.retry_options
        assert options is not None
        assert options.attempts == 3
        assert options.max_delay == 20.0

    def test_google_zero_disables_retrying(self) -> None:
        model = build_model(
            "cloud:gemini-3-flash-preview",
            agent_settings=AgentSettings(transient_retries=0),
            settings=_settings(gemini_api_key=SecretStr("gk-test")),
        )
        assert model.client._api_client._http_options.retry_options is None

    def test_anthropic_client_carries_the_retries(self) -> None:
        model = build_model(
            "cloud:claude-sonnet-5",
            agent_settings=AgentSettings(transient_retries=4),
            settings=_settings(anthropic_api_key=SecretStr("sk-test")),
        )
        assert model.client.max_retries == 4

    def test_local_client_carries_the_retries(self) -> None:
        """The vLLM container restarting is exactly the case this covers."""
        model = build_model(
            "local:qwen3-4b",
            agent_settings=AgentSettings(transient_retries=4),
            settings=_settings(),
        )
        assert model.client.max_retries == 4


def test_bad_spec_raises_before_touching_a_provider() -> None:
    with pytest.raises(ConfigError):
        build_model("gpu:qwen3-4b", settings=_settings())
