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

**One provider, several keys.** Each provider has a `KeyRing` — see `llm/keyring.py` —
built once per process and asked for a key each time a model is built. Several keys are
several accounts and so several quotas, which on a free tier is the difference between
twenty requests a day and sixty. The ring is module state on purpose: one that is rebuilt
per call forgets which key it just found spent.

**One model being down is not the same problem as one key being spent.** A 429 means our
quota; the key ring answers it, and moving to another model there would spend a second
quota while the ring still has keys. A 503 or a 504 means the provider's side is
overloaded, and no key helps — on 2026-09-24 all three keys would have met the same 503.
So an agent may name `fallback_specs`, and `build_model` returns a `FallbackModel` that
walks them in order on exactly that class of failure. See `_is_unavailable`.

**Transient HTTP failures are retried by the provider's own client.** A 503 from an
overloaded model, a 429, a dropped connection — each SDK already knows how to wait and
resend the single failed request, so `transient_retries` is handed to that machinery rather
than wrapped around the agent loop, which would replay the whole conversation and pay for
every token again. Only failures the SDK gives up on reach `exceptions.py`.

Building a model makes no network call, so agents can be constructed at import time.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.exceptions import caused_by_timeout
from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError
from mycel.llm.keyring import KeyRing
from mycel.llm.router import ModelSpec, Tier, resolve

if TYPE_CHECKING:  # Type-visible without importing an SDK at runtime.
    from google.genai.types import HttpRetryOptions
    from pydantic_ai.models import Model
    from pydantic_ai.settings import ModelSettings


@dataclass(frozen=True, slots=True)
class _Backend:
    """What a spec name resolves to: the provider's own model id, and how to reach it."""

    model_name: str
    provider: Literal["google", "anthropic"]


#: Which variable a provider's keys are written in. Named here rather than on `_Backend`
#: because it is a property of the provider, and repeating it on every model is six places
#: to keep in step for no gain.
_ENV_VARS: dict[str, str] = {"google": "GEMINI_API_KEYS", "anthropic": "ANTHROPIC_API_KEY"}

#: One ring per provider, for the life of the process. Rebuilding it per call would lose
#: the memory of which key was just found spent, which is the only thing a ring is for.
_RINGS: dict[str, KeyRing] = {}


def key_ring(provider: str, env: Settings) -> KeyRing:
    """This provider's keys, built once.

    Exposed rather than private so a test can clear `_RINGS` and so a caller that has just
    been refused by the API can bench the key it was given.
    """
    if provider not in _RINGS:
        _RINGS[provider] = KeyRing.of(provider, _ENV_VARS[provider], env.llm_keys(provider))
    return _RINGS[provider]


def reset_key_rings() -> None:
    """Forget every ring. For tests, and for a process that has reloaded its settings."""
    _RINGS.clear()


#: Where a built model remembers the key it was given. On the instance rather than in
#: module state, because two runs build two models and a shared "last key" would bench
#: whichever key the other one happened to use.
_KEY_ATTR = "_mycel_key"
_PROVIDER_ATTR = "_mycel_provider"

#: A daily quota and a per-minute rate limit arrive under the same status code and must not
#: be treated alike: bench an exhausted key for a minute and it comes back, earns another
#: 429, and the ring spins all day without one request succeeding. Google says which in the
#: body, so the body is what is read.
_EXHAUSTED_MARKERS = ("quota", "exhausted", "resource_exhausted", "per day", "daily limit")


def note_failure(model: "Model", exc: BaseException) -> None:
    """Bench the key this model used, if the provider's answer was about the key.

    Called from the one place that sees a provider error with the model still in hand. A
    failure that is not about credentials — a 500, a timeout, a bad request — leaves the
    ring alone: benching a healthy key over someone else's outage throws quota away.

    A `FallbackModel` holds several real models and raises a group, so it is unpacked into
    the pairs that actually happened: each error carries the name of the model that raised
    it, and that model carries the key it was given.
    """
    if isinstance(model, _fallback_type()):
        for inner, cause in _blamed(model, exc):
            _note_one(inner, cause)
        return
    _note_one(model, exc)


def _fallback_type() -> type:
    """`FallbackModel`, imported late like every other SDK name in this module."""
    from pydantic_ai.models.fallback import FallbackModel

    return FallbackModel


#: Statuses that mean "the provider could not serve this request", as opposed to "your
#: request was wrong" or "your quota is gone". Only these move to the next model: falling
#: over on a 400 would ask a second model the same malformed question, and falling over on
#: a 429 would spend a second account's quota while the key ring still has keys for this
#: one.
_UNAVAILABLE_STATUS = (500, 502, 503, 504)


def _is_unavailable(exc: Exception) -> bool:
    """Whether this failure is the provider being down rather than us being wrong.

    A timeout counts: nothing was served, and the next model is the only thing that can
    change that. This is the whole `fallback_on` rule, kept in one readable predicate
    rather than spread over a tuple of exception classes.
    """
    from pydantic_ai.exceptions import ModelHTTPError

    if isinstance(exc, ModelHTTPError):
        return exc.status_code in _UNAVAILABLE_STATUS
    return caused_by_timeout(exc)


def _blamed(model: "Model", exc: BaseException) -> list[tuple["Model", BaseException]]:
    """Which of a fallback's models earned which error.

    Empty for an ordinary model, whose one error is its own. Matching is by model name
    because that is what `ModelAPIError` carries; a chain naming the same model twice would
    bench the same key twice, which is harmless.
    """
    from pydantic_ai.exceptions import FallbackExceptionGroup, ModelAPIError
    from pydantic_ai.models.fallback import FallbackModel

    if not isinstance(model, FallbackModel):
        return []
    causes = exc.exceptions if isinstance(exc, FallbackExceptionGroup) else (exc,)
    pairs: list[tuple[Model, BaseException]] = []
    for cause in causes:
        if not isinstance(cause, ModelAPIError):
            continue
        for inner in model.models:
            if inner.model_name == cause.model_name:
                pairs.append((inner, cause))
                break
    return pairs


def _note_one(model: "Model", exc: BaseException) -> None:
    """The original single-model bench, unchanged."""
    from pydantic_ai.exceptions import ModelHTTPError

    key = getattr(model, _KEY_ATTR, None)
    provider = getattr(model, _PROVIDER_ATTR, None)
    if key is None or provider is None or not isinstance(exc, ModelHTTPError):
        return

    ring = _RINGS.get(provider)
    if ring is None:  # pragma: no cover - a model exists only if its ring did
        return

    if exc.status_code == 429:
        body = str(exc.body).lower()
        if any(marker in body for marker in _EXHAUSTED_MARKERS):
            ring.bench_exhausted(key)
        else:
            ring.bench_rate_limited(key)
    elif exc.status_code in (401, 403):
        # The key itself is refused, so no amount of waiting helps. 403 can also mean the
        # API is not enabled for the project, which is equally permanent for this process.
        ring.bench_rejected(key)


def _remember_key(model: "Model", provider: str, api_key: str) -> "Model":
    """Tag a model with the credential behind it, so a later 429 knows what to bench."""
    object.__setattr__(model, _PROVIDER_ATTR, provider)
    object.__setattr__(model, _KEY_ATTR, api_key)
    return model


# Specs stay short and human-sized, so pinning a dated version is an edit here rather than
# across every agent's config.
_CLOUD_MODELS: dict[str, _Backend] = {
    "gemini-3.8-flash": _Backend("gemini-3.8-flash", "google"),
    "gemini-3.6-flash": _Backend("gemini-3.6-flash", "google"),
    "gemini-3.5-flash-lite": _Backend("gemini-3.5-flash-lite", "google"),
    # Preview, and priced as one: the free tier allows 20 requests a day for this model
    # against far more for the GA releases above. Kept for comparison, not for running.
    "gemini-3-flash-preview": _Backend("gemini-3-flash-preview", "google"),
    "claude-sonnet-5": _Backend("claude-sonnet-5", "anthropic"),
    "claude-haiku-4-5": _Backend("claude-haiku-4-5-20251001", "anthropic"),
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

    With `fallback_specs` set, the result is a `FallbackModel` over `spec` and then each
    of them in turn. Every one of them is built here and now — a chain whose second model
    is only constructed once the first fails would do its config check during an outage,
    which is the worst moment to discover a typo.

    Raises `ConfigError` when the model is unknown or its credential is not set — at build
    time, not on the first call, so a misconfigured deployment fails at startup.
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
    """One spec, one client. The link in the chain, and the whole of it when there is no
    chain."""
    resolved = resolve(spec)
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

    ring = key_ring(backend.provider, env)
    if not ring:
        # Named here rather than in the ring, which knows its variable but not which spec
        # asked for it — and the spec is what the reader has to go and edit.
        raise ConfigError(
            f"{_ENV_VARS[backend.provider]} is not set, but model spec {spec} needs it"
        )
    api_key = ring.take()
    model_settings = _model_settings(agent_cfg, backend.model_name)

    if backend.provider == "google":
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        return _remember_key(
            GoogleModel(
                backend.model_name,
                provider=GoogleProvider(api_key=api_key, retry_options=_google_retries(agent_cfg)),
                settings=model_settings,
            ),
            backend.provider,
            api_key,
        )

    from anthropic import AsyncAnthropic
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    # `max_retries` lives on the client, not the provider, so the client is built here.
    client = AsyncAnthropic(api_key=api_key, max_retries=agent_cfg.transient_retries)
    return _remember_key(
        AnthropicModel(
            backend.model_name,
            provider=AnthropicProvider(anthropic_client=client),
            settings=model_settings,
        ),
        backend.provider,
        api_key,
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
        agent_cfg.transient_retries,
    )


def _openai_chat_model(
    model_name: str,
    base_url: str,
    api_key: str,
    model_settings: "ModelSettings",
    transient_retries: int,
) -> "Model":
    """The local server: vLLM speaks /v1/chat/completions and nothing else."""
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=transient_retries)
    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(openai_client=client),
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


def _google_retries(agent_cfg: AgentSettings) -> "HttpRetryOptions | None":
    """google-genai counts `attempts` including the first, unlike the other two SDKs.

    Returns `None` for zero retries: the SDK reads that as "never retry", where
    `attempts=1` would mean the same thing by a longer route.
    """
    from google.genai.types import HttpRetryOptions

    if agent_cfg.transient_retries <= 0:
        return None
    return HttpRetryOptions(
        attempts=agent_cfg.transient_retries + 1,
        max_delay=agent_cfg.retry_max_delay_s,
    )
