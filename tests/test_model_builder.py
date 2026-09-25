"""Spec strings become real provider clients, with the right endpoint and credentials.

Every assertion is on the constructed object. Nothing here sends a request — `conftest.py`
sets `ALLOW_MODEL_REQUESTS = False`, and building a model must not need the network anyway.
"""

import pytest
from pydantic import SecretStr
from pydantic_ai.exceptions import FallbackExceptionGroup, ModelAPIError, ModelHTTPError
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel

from mycel.agents.core.config import AgentSettings
from mycel.agents.core.exceptions import (
    ModelCallFailed,
    ModelTimeout,
    TransportError,
    translate_agent_errors,
)
from mycel.agents.core.model_builder import (
    _is_unavailable,
    build_model,
    key_ring,
    note_failure,
    reset_key_rings,
)
from mycel.core.config import Settings
from mycel.core.exceptions import ConfigError


def _settings(**kwargs: object) -> Settings:
    return Settings(**kwargs)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _fresh_key_rings() -> None:
    """A key ring is built once per process and remembers what it found spent, so a test
    that inherits one from the test before it is reading another test's keys."""
    reset_key_rings()


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
        with pytest.raises(ConfigError, match="GEMINI_API_KEYS"):
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


class TestFallbackChain:
    """One model being down is a different problem from one key being spent.

    Batch 053 answered the quota half: a 429 rotates to the next key. This is the half
    rotation cannot touch — on 2026-09-24 three keys aimed at an overloaded model all got
    the same 503 — so the run moves to another model instead. The line between the two is
    what these tests pin, because putting it in the wrong place is expensive both ways:
    fall over on a 429 and a second account's quota is spent while the ring still had
    keys; refuse to fall over on a 503 and the outage stops everything again.
    """

    def test_no_fallbacks_is_still_one_plain_model(self) -> None:
        """The shape every agent had before this batch, and the shape a test or a script
        that names no fallback still gets."""
        model = build_model(
            "cloud:gemini-3.6-flash", settings=_settings(gemini_api_key=SecretStr("gk-test"))
        )
        assert isinstance(model, GoogleModel)

    def test_the_chain_is_built_in_the_order_it_was_written(self) -> None:
        model = build_model(
            "cloud:gemini-3.5-flash-lite",
            AgentSettings(fallback_specs=("cloud:gemini-3.6-flash", "cloud:gemini-3.8-flash")),
            settings=_settings(gemini_api_key=SecretStr("gk-test")),
        )
        assert isinstance(model, FallbackModel)
        assert [inner.model_name for inner in model.models] == [
            "gemini-3.5-flash-lite",
            "gemini-3.6-flash",
            "gemini-3.8-flash",
        ]

    def test_a_typo_in_a_fallback_fails_at_build_time(self) -> None:
        """Every model in the chain is constructed now, not when the first one fails. A
        chain that checks its spare's configuration during an outage discovers the typo at
        the worst possible moment."""
        with pytest.raises(ConfigError, match="gemini-9-imaginary"):
            build_model(
                "cloud:gemini-3.6-flash",
                AgentSettings(fallback_specs=("cloud:gemini-9-imaginary",)),
                settings=_settings(gemini_api_key=SecretStr("gk-test")),
            )

    def test_a_fallback_may_be_the_local_model(self) -> None:
        """Nothing here is Google-specific: the spare is a spec like any other, and a
        machine with vLLM running has an answer to a whole-of-Google outage."""
        model = build_model(
            "cloud:gemini-3.6-flash",
            AgentSettings(fallback_specs=("local:qwen3-4b",)),
            settings=_settings(gemini_api_key=SecretStr("gk-test")),
        )
        assert isinstance(model, FallbackModel)
        assert isinstance(model.models[1], OpenAIChatModel)

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_the_provider_being_down_moves_to_the_next_model(self, status: int) -> None:
        assert _is_unavailable(ModelHTTPError(model_name="m", status_code=status, body=None))

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    def test_our_own_bad_request_does_not(self, status: int) -> None:
        """Asking a second model the same malformed question gets the same answer, and a
        401 means the key is refused — which the key ring handles, not this."""
        assert not _is_unavailable(ModelHTTPError(model_name="m", status_code=status, body=None))

    def test_a_spent_quota_does_not_move_to_the_next_model(self) -> None:
        """The one that would be tempting and wrong. 429 is our quota, and the key ring
        has two more keys for it; falling to another model spends a second account's day
        while the first still had requests left."""
        assert not _is_unavailable(ModelHTTPError(model_name="m", status_code=429, body="quota"))

    def test_a_timeout_moves_to_the_next_model(self) -> None:
        """Nothing was served, and waiting is the one thing that has already been tried."""
        assert _is_unavailable(ModelAPIError("m", "timed out")) is False
        timed_out = ModelAPIError("m", "timed out")
        timed_out.__cause__ = TimeoutError()
        assert _is_unavailable(timed_out)


class TestWhenTheWholeChainFails:
    """`FallbackModel` raises a `FallbackExceptionGroup`, which is not a `ModelAPIError`.

    Left untranslated it would walk straight past the clause batch 054 added and arrive at
    `tools/delegate.py` as an ordinary exception — narrated as prose, billed, marked done.
    That is the exact failure 054 closed, re-opened by a different exception class.
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


class TestBenchingAKeyBehindAChain:
    """`note_failure` used to see one model and one error. A chain hands it several of
    each, and getting the pairing wrong benches a key that did nothing."""

    def _chain(self) -> FallbackModel:
        model = build_model(
            "cloud:gemini-3.5-flash-lite",
            AgentSettings(fallback_specs=("cloud:gemini-3.6-flash",)),
            settings=_settings(gemini_api_keys="k1,k2"),
        )
        assert isinstance(model, FallbackModel)
        return model

    def test_a_429_benches_the_key_of_the_model_that_earned_it(self) -> None:
        chain = self._chain()
        ring = key_ring("google", _settings(gemini_api_keys="k1,k2"))
        before = len(ring)

        note_failure(
            chain,
            FallbackExceptionGroup(
                "failed",
                [ModelHTTPError(model_name="gemini-3.6-flash", status_code=429, body="quota")],
            ),
        )

        assert before == len(ring), "benching must not remove a key, only rest it"
        # The key the second model was given is the one that is now resting.
        spent = chain.models[1]._mycel_key  # type: ignore[attr-defined]
        assert any(k.value == spent and k.rested_until for k in ring._keys)

    def test_a_503_benches_nothing(self) -> None:
        """The provider was overloaded, not the key. Benching a healthy key over someone
        else's outage throws quota away for the rest of the day."""
        chain = self._chain()
        ring = key_ring("google", _settings(gemini_api_keys="k1,k2"))

        note_failure(
            chain,
            FallbackExceptionGroup(
                "failed",
                [ModelHTTPError(model_name="gemini-3.5-flash-lite", status_code=503, body=None)],
            ),
        )

        assert all(key.rested_until is None for key in ring._keys)
