"""Turn a `'<tier>:<model_name>'` spec into a model client ready to call.

Parse the spec, ask `llm/router.py` which tier it is, map the name onto what the backend
calls it, pick up the matching credential. This is the only place that knows which provider
needs which parameters — an agent just receives something callable.

It is therefore the single documented exception to "never import a provider SDK directly"
(see `llm/router.py`).

**Each cloud provider gets its native client; only the local server speaks OpenAI.** The
tempting shortcut is one client shape for everything, since Gemini publishes an
OpenAI-compatible endpoint — but that endpoint drops Gemini 3's `thought_signature`, and
the API then rejects any run that calls a tool. Every agent here calls tools, so the
compatibility layer is not an option. vLLM has no native client and needs none.

Not `LiteLLMProvider` either: despite the name it does not route through the LiteLLM SDK,
it builds an OpenAI client against a LiteLLM **proxy server** — another container to run,
and the same compatibility layer at the end of it.

**Sampling parameters are not universal.** Gemini 3 and later reject `temperature`,
`top_p` and `top_k` rather than ignoring them, so a value configured for a model that has
no such knob is dropped here. Configuration stays declarative; the backend's rules stay in
this file.

Building a model makes no network call, so agents can be constructed at import time.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from mycel.agents.core.config import AgentSettings
from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError
from mycel.llm.router import ModelSpec, Tier, resolve

if TYPE_CHECKING:  # Type-visible without importing an SDK at runtime.
    from pydantic_ai.models import Model
    from pydantic_ai.settings import ModelSettings


@dataclass(frozen=True, slots=True)
class _Backend:
    """What a spec name resolves to: the provider's own model id, and how to reach it."""

    model_name: str
    provider: Literal["google", "anthropic"]
    key_field: str
    env_var: str


# Specs stay short and human-sized, so pinning a dated version is an edit here rather than
# across every agent's config.
_CLOUD_MODELS: dict[str, _Backend] = {
    "gemini-3.8-flash": _Backend("gemini-3.8-flash", "google", "gemini_api_key", "GEMINI_API_KEY"),
    "gemini-3.6-flash": _Backend("gemini-3.6-flash", "google", "gemini_api_key", "GEMINI_API_KEY"),
    "gemini-3.5-flash-lite": _Backend(
        "gemini-3.5-flash-lite", "google", "gemini_api_key", "GEMINI_API_KEY"
    ),
    # Preview, and priced as one: the free tier allows 20 requests a day for this model
    # against far more for the GA releases above. Kept for comparison, not for running.
    "gemini-3-flash-preview": _Backend(
        "gemini-3-flash-preview", "google", "gemini_api_key", "GEMINI_API_KEY"
    ),
    "claude-sonnet-5": _Backend(
        "claude-sonnet-5", "anthropic", "anthropic_api_key", "ANTHROPIC_API_KEY"
    ),
    "claude-haiku-4-5": _Backend(
        "claude-haiku-4-5-20251001", "anthropic", "anthropic_api_key", "ANTHROPIC_API_KEY"
    ),
}

# The local server runs whatever the compose file pins.
_LOCAL_MODELS: dict[str, str] = {
    "qwen3-4b": "Qwen/Qwen2.5-3B-Instruct-AWQ",
}

# Models that reject the sampling parameters instead of ignoring them.
_NO_SAMPLING_PREFIXES = ("gemini-3",)


def build_model(
    spec: str,
    agent_settings: AgentSettings | None = None,
    settings: Settings | None = None,
) -> "Model":
    """`'<tier>:<name>'` -> a configured pydantic-ai `Model`.

    Raises `ConfigError` when the model is unknown or its credential is not set — at build
    time, not on the first call, so a misconfigured deployment fails at startup.
    """
    resolved = resolve(spec)
    agent_cfg = agent_settings or AgentSettings()
    env = settings or get_settings()

    if resolved.tier is Tier.LOCAL:
        return _local_model(resolved, env, agent_cfg)
    return _cloud_model(resolved, env, agent_cfg)


def _cloud_model(spec: ModelSpec, env: Settings, agent_cfg: AgentSettings) -> "Model":
    try:
        backend = _CLOUD_MODELS[spec.name]
    except KeyError:
        known = ", ".join(sorted(_CLOUD_MODELS))
        raise ConfigError(
            f"unknown cloud model {spec.name!r} in spec {spec}; known models: {known}"
        ) from None

    secret = getattr(env, backend.key_field)
    if secret is None:
        raise ConfigError(f"{backend.env_var} is not set, but model spec {spec} needs it")
    api_key = secret.get_secret_value()
    model_settings = _model_settings(agent_cfg, backend.model_name)

    if backend.provider == "google":
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        return GoogleModel(
            backend.model_name,
            provider=GoogleProvider(api_key=api_key),
            settings=model_settings,
        )

    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    return AnthropicModel(
        backend.model_name,
        provider=AnthropicProvider(api_key=api_key),
        settings=model_settings,
    )


def _local_model(spec: ModelSpec, env: Settings, agent_cfg: AgentSettings) -> "Model":
    """The vLLM server ignores the key, but the client insists on one, so a placeholder
    goes in rather than a credential that does not exist."""
    model_name = _LOCAL_MODELS.get(spec.name, spec.name)
    return _openai_chat_model(
        model_name,
        env.local_llm_base_url,
        "not-needed",
        _model_settings(agent_cfg, model_name),
    )


def _openai_chat_model(
    model_name: str, base_url: str, api_key: str, model_settings: "ModelSettings"
) -> "Model":
    """The local server: vLLM speaks /v1/chat/completions and nothing else."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(base_url=base_url, api_key=api_key),
        settings=model_settings,
    )


def _model_settings(agent_cfg: AgentSettings, model_name: str) -> "ModelSettings":
    """Generation settings the chosen model actually accepts."""
    from pydantic_ai.settings import ModelSettings

    model_settings = ModelSettings(timeout=agent_cfg.timeout_s)
    if not model_name.startswith(_NO_SAMPLING_PREFIXES):
        model_settings["temperature"] = agent_cfg.temperature
    if agent_cfg.max_tokens is not None:
        model_settings["max_tokens"] = agent_cfg.max_tokens
    return model_settings
