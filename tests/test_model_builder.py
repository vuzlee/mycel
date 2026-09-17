"""Spec strings become real provider clients, with the right endpoint and credentials.

Every assertion is on the constructed object. Nothing here sends a request — `conftest.py`
sets `ALLOW_MODEL_REQUESTS = False`, and building a model must not need the network anyway.
"""

import pytest
from pydantic import SecretStr
from pydantic_ai.models.anthropic import AnthropicModel
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


def test_bad_spec_raises_before_touching_a_provider() -> None:
    with pytest.raises(ConfigError):
        build_model("gpu:qwen3-4b", settings=_settings())
