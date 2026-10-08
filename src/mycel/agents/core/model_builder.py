"""Turn a `'<tier>:<model_name>'` spec into a pydantic-ai model behind the LiteLLM gateway.

Building a model makes no network call, so agents can be constructed at import time.
"""

from typing import TYPE_CHECKING

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.exceptions import caused_by_timeout
from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError
from mycel.llm.router import resolve

if TYPE_CHECKING:
    from pydantic_ai.models import Model
    from pydantic_ai.settings import ModelSettings

#: Statuses that move to the next fallback model; a 429 means LiteLLM already tried every key.
_UNAVAILABLE_STATUS = (429, 500, 502, 503, 504)


def build_model(
    spec: str,
    agent_settings: AgentSettings | None = None,
    settings: Settings | None = None,
) -> "Model":
    """Build the model, wrapped in a `FallbackModel` when `fallback_specs` is set."""
    agent_cfg = agent_settings or AgentSettings()
    env = settings or get_settings()

    primary = _one_model(spec, env, agent_cfg)
    if not agent_cfg.fallback_specs:
        return primary

    from pydantic_ai.models.fallback import FallbackModel

    spares = [_one_model(other, env, agent_cfg) for other in agent_cfg.fallback_specs]
    return FallbackModel(primary, *spares, fallback_on=_is_unavailable)


def _one_model(spec: str, env: Settings, agent_cfg: AgentSettings) -> "Model":
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.litellm import LiteLLMProvider

    name = resolve(spec).name
    if not env.litellm_base_url:
        raise ConfigError(f"litellm_base_url is not set, but model spec {spec} needs it")
    key = env.litellm_api_key.get_secret_value() if env.litellm_api_key else "not-needed"
    client = AsyncOpenAI(
        base_url=env.litellm_base_url, api_key=key, max_retries=agent_cfg.transient_retries
    )
    return OpenAIChatModel(
        name,
        provider=LiteLLMProvider(openai_client=client),
        settings=_model_settings(agent_cfg),
    )


def _is_unavailable(exc: Exception) -> bool:
    """Whether the next model in the chain could change the outcome."""
    from pydantic_ai.exceptions import ModelHTTPError

    if isinstance(exc, ModelHTTPError):
        return exc.status_code in _UNAVAILABLE_STATUS
    return caused_by_timeout(exc)


def _model_settings(agent_cfg: AgentSettings) -> "ModelSettings":
    """Temperature goes out for every model; the gateway drops it where unsupported."""
    from pydantic_ai.settings import ModelSettings

    model_settings = ModelSettings(timeout=agent_cfg.timeout_s, temperature=agent_cfg.temperature)
    if agent_cfg.max_tokens is not None:
        model_settings["max_tokens"] = agent_cfg.max_tokens
    return model_settings
