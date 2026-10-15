"""Turn a `'<tier>:<model_name>'` spec into a pydantic-ai model behind the LiteLLM gateway.

Building a model makes no network call, so agents can be constructed at import time.
"""

import asyncio
from typing import TYPE_CHECKING, Any

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.own_endpoint import OwnEndpoint
from mycel.agents.core.rotating import OnFailure, RotatingModel
from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError
from mycel.llm.router import resolve

if TYPE_CHECKING:
    from openai import AsyncOpenAI
    from pydantic_ai.models import Model
    from pydantic_ai.settings import ModelSettings

#: One client (and its connection pool) per gateway, key and retry count, per event loop:
#: a client built for every run never reused a connection and was never closed.
_clients: dict[tuple[int, str, str, int], "AsyncOpenAI"] = {}


def build_model(
    spec: str,
    agent_settings: AgentSettings | None = None,
    settings: Settings | None = None,
) -> "Model":
    """One model, no fallback: a failure names this model and why."""
    agent_cfg = agent_settings or AgentSettings()
    env = settings or get_settings()

    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.litellm import LiteLLMProvider

    name = resolve(spec).name
    if not env.litellm_base_url:
        raise ConfigError(f"litellm_base_url is not set, but model spec {spec} needs it")
    key = env.litellm_api_key.get_secret_value() if env.litellm_api_key else "not-needed"
    client = _client(env.litellm_base_url, key, agent_cfg.transient_retries)
    return OpenAIChatModel(
        name,
        provider=LiteLLMProvider(openai_client=client),
        settings=_model_settings(agent_cfg),
    )


def _client(base_url: str, key: str, retries: int) -> "AsyncOpenAI":
    from openai import AsyncOpenAI

    try:
        loop = id(asyncio.get_running_loop())
    except RuntimeError:
        loop = 0
    found = _clients.get((loop, base_url, key, retries))
    if found is None:
        found = AsyncOpenAI(base_url=base_url, api_key=key, max_retries=retries)
        _clients[(loop, base_url, key, retries)] = found
    return found


async def close_clients() -> None:
    """Close every gateway client; the next run builds fresh ones."""
    clients = list(_clients.values())
    _clients.clear()
    for client in clients:
        await client.close()


def _model_settings(agent_cfg: AgentSettings) -> "ModelSettings":
    """Temperature goes out for every model; the gateway drops it where unsupported."""
    from pydantic_ai.settings import ModelSettings

    model_settings = ModelSettings(timeout=agent_cfg.timeout_s, temperature=agent_cfg.temperature)
    if agent_cfg.max_tokens is not None:
        model_settings["max_tokens"] = agent_cfg.max_tokens
    return model_settings


#: Own models skip the gateway, so the app's client is the only one retrying.
OWN_RETRIES = 2

#: Tests swap in a mock transport; None is the real network.
_transport: Any = None


def build_own_model(
    own: OwnEndpoint, agent_cfg: AgentSettings, on_failure: OnFailure
) -> "tuple[Model, list[AsyncOpenAI]]":
    """One client per key, for this run only: a person's key never sits in a shared cache.

    Returns the clients too, so the caller closes them when the run ends. Redirects are not
    followed: a checked base URL must not hand the request on to an address it was not.
    """
    from openai import AsyncOpenAI, DefaultAsyncHttpxClient
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    clients = [
        AsyncOpenAI(
            base_url=own.api_base,
            api_key=key.get_secret_value(),
            max_retries=OWN_RETRIES,
            http_client=DefaultAsyncHttpxClient(follow_redirects=False, transport=_transport),
        )
        for _, key in own.keys
    ]
    keyed = [
        (
            position,
            OpenAIChatModel(
                own.endpoint_model,
                provider=OpenAIProvider(openai_client=client),
                settings=_model_settings(agent_cfg),
            ),
        )
        for (position, _), client in zip(own.keys, clients, strict=True)
    ]
    return RotatingModel(keyed, on_failure), clients
