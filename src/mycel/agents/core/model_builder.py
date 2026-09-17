"""Turn a `'<tier>:<model_name>'` spec into a model client ready to call.

Parse the spec, ask `llm/router.py` which tier it is, pick up the matching credentials,
return a client with timeout and retry count already set. This is the only place that
knows which provider needs which parameters — `agent.py` just receives something callable.

It is therefore the single documented exception to "never import a provider SDK directly"
(see `llm/router.py`). The imports are function-local so that importing this module does
not pull in both SDKs when only one tier is in use.

Building a model makes no network call, so agents can be constructed at import time.
"""

from typing import TYPE_CHECKING

from mycel.agents.core.config import AgentSettings
from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError
from mycel.llm.router import ModelSpec, Tier, resolve

if TYPE_CHECKING:  # Type-visible without importing an SDK at runtime.
    from pydantic_ai.models import Model
    from pydantic_ai.settings import ModelSettings

# The local server runs whatever the compose file pins; specs stay short and human-sized.
# Renaming the served model is an edit here, not across every agent.
_LOCAL_ALIASES: dict[str, str] = {
    "qwen3-4b": "Qwen/Qwen2.5-3B-Instruct-AWQ",
}


def build_model(
    spec: str,
    agent_settings: AgentSettings | None = None,
    settings: Settings | None = None,
) -> "Model":
    """`'<tier>:<name>'` -> a configured pydantic-ai `Model`.

    Raises `ConfigError` when the tier needs a credential that is not set — at build time,
    not on the first call, so a misconfigured deployment fails at startup.
    """
    from pydantic_ai.settings import ModelSettings

    resolved = resolve(spec)
    agent_cfg = agent_settings or AgentSettings()
    env = settings or get_settings()

    model_settings = ModelSettings(
        temperature=agent_cfg.temperature,
        timeout=agent_cfg.timeout_s,
    )
    if agent_cfg.max_tokens is not None:
        model_settings["max_tokens"] = agent_cfg.max_tokens

    if resolved.tier is Tier.CLOUD:
        return _build_cloud(resolved, env, model_settings)
    return _build_local(resolved, env, model_settings)


def _build_cloud(
    spec: ModelSpec, env: Settings, model_settings: "ModelSettings"
) -> "Model":
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    if env.anthropic_api_key is None:
        raise ConfigError(
            f"ANTHROPIC_API_KEY is not set, but model spec {spec} needs the cloud tier"
        )

    return AnthropicModel(
        spec.name,
        provider=AnthropicProvider(api_key=env.anthropic_api_key.get_secret_value()),
        settings=model_settings,
    )


def _build_local(
    spec: ModelSpec, env: Settings, model_settings: "ModelSettings"
) -> "Model":
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    return OpenAIChatModel(
        _LOCAL_ALIASES.get(spec.name, spec.name),
        # vLLM speaks /v1/chat/completions, so the chat model rather than the responses
        # one. It ignores the key, but the OpenAI SDK refuses to start without a value.
        provider=OpenAIProvider(base_url=env.local_llm_base_url, api_key="not-needed"),
        settings=model_settings,
    )
