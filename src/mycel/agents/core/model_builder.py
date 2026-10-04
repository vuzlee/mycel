"""Turn a `'<tier>:<model_name>'` spec into a model client ready to call.

Every model is reached through one gateway, the LiteLLM proxy, over the OpenAI Chat
Completions API. `<model_name>` is a `model_name` in `config/litellm/config.yaml`; which
provider sits behind it, which keys it rotates through and how it cools a spent key down
are that file's business. Changing model is a config edit, never a code change.

This is the single documented exception to "never import a provider SDK directly"
(see `llm/router.py`).

Gemini 3 needs its `thought_signature` returned on every tool call. Its own
OpenAI-compatible endpoint drops it; LiteLLM keeps it inside the tool call id, which the
client sends back unchanged. Checked on 2026-10-05 with two-turn tool calls, plain and
streamed, for Gemini 3.5 Flash Lite and Claude Sonnet 5.

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

#: Statuses that mean "this model could not serve the request", as opposed to "the request
#: was wrong". Only these move to the next model in `fallback_specs`. A 429 is included:
#: LiteLLM has already tried every key it holds for this model before it says so.
_UNAVAILABLE_STATUS = (429, 500, 502, 503, 504)


def build_model(
    spec: str,
    agent_settings: AgentSettings | None = None,
    settings: Settings | None = None,
) -> "Model":
    """`'<tier>:<name>'` -> a pydantic-ai `Model` that calls the gateway.

    With `fallback_specs` set, the result is a `FallbackModel` over `spec` and then each of
    them in turn, all built here so a typo fails at startup rather than during an outage.
    """
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
