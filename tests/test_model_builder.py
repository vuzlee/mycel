"""One client for every model: OpenAI Chat Completions to the LiteLLM gateway."""

import pytest
from pydantic_ai.models.openai import OpenAIChatModel

from mycel.agents.core import model_builder
from mycel.agents.core.model_builder import build_model
from mycel.agents.core.settings import AgentSettings
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
        assert isinstance(model, OpenAIChatModel)
        assert model.client.api_key == "sk-gateway"

    def test_no_gateway_is_a_config_error(self) -> None:
        with pytest.raises(ConfigError, match="litellm_base_url"):
            build_model("cloud:claude-sonnet-5", settings=_settings(litellm_base_url=""))

    def test_a_bad_spec_raises_before_any_call(self) -> None:
        with pytest.raises(ConfigError):
            build_model("gpu:qwen3-4b", settings=_settings())


@pytest.mark.anyio
class TestClientsAreShared:
    async def test_runs_reuse_one_client_per_gateway(self) -> None:
        """A client per run never reused a connection, and none was ever closed."""
        first = build_model("cloud:claude-sonnet-5", settings=_settings())
        second = build_model("cloud:gemini-3.6-flash", settings=_settings())

        assert isinstance(first, OpenAIChatModel) and isinstance(second, OpenAIChatModel)
        assert first.client is second.client
        await model_builder.close_clients()

    async def test_a_different_key_gets_its_own_client(self) -> None:
        first = build_model("cloud:claude-sonnet-5", settings=_settings(litellm_api_key="a"))
        second = build_model("cloud:claude-sonnet-5", settings=_settings(litellm_api_key="b"))

        assert isinstance(first, OpenAIChatModel) and isinstance(second, OpenAIChatModel)
        assert first.client is not second.client
        await model_builder.close_clients()

    async def test_closing_starts_over(self) -> None:
        first = build_model("cloud:claude-sonnet-5", settings=_settings())
        await model_builder.close_clients()
        second = build_model("cloud:claude-sonnet-5", settings=_settings())

        assert isinstance(first, OpenAIChatModel) and isinstance(second, OpenAIChatModel)
        assert first.client is not second.client
        await model_builder.close_clients()


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
        assert isinstance(model, OpenAIChatModel)
        assert model.client.max_retries == 4


class TestOneModel:
    def test_it_is_one_plain_model(self) -> None:
        """No fallback chain: a failure names this model and why."""
        assert isinstance(
            build_model("cloud:claude-sonnet-5", settings=_settings()), OpenAIChatModel
        )

    def test_the_gateway_path_does_not_retry_by_default(self) -> None:
        """The gateway retries; a second layer would multiply the calls."""
        model = build_model("cloud:claude-sonnet-5", settings=_settings())
        assert isinstance(model, OpenAIChatModel)
        assert model.client.max_retries == 0
