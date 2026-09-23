"""Tracing setup. Nothing is exported: these check the switch and the wiring."""

import base64
from typing import Any

import pytest
from pydantic import SecretStr

from mycel.core.config import Settings
from mycel.core.exceptions import ConfigError
from mycel.observability import tracing


@pytest.fixture(autouse=True)
def _reset() -> "object":
    tracing.reset_for_tests()
    yield
    tracing.reset_for_tests()


def _settings(**kw: Any) -> Settings:
    return Settings(
        otel_exporter_otlp_endpoint="http://localhost:4318/v1/traces",
        **kw,
    )


class TestDisabled:
    def test_returns_none_when_off(self) -> None:
        """Development runs without standing up a collector; that must cost nothing."""
        assert tracing.setup_tracing(_settings(otel_enabled=False)) is None

    def test_off_is_the_default(self) -> None:
        assert Settings().otel_enabled is False


class TestEnabled:
    def test_installs_a_provider(self) -> None:
        from opentelemetry.sdk.trace import TracerProvider

        provider = tracing.setup_tracing(_settings(otel_enabled=True))
        assert isinstance(provider, TracerProvider)

    def test_service_name_reaches_the_resource(self) -> None:
        """A trace that cannot say which service emitted it is not much of a trace."""
        provider = tracing.setup_tracing(
            _settings(otel_enabled=True, otel_service_name="mycel-worker")
        )
        assert provider is not None
        assert provider.resource.attributes["service.name"] == "mycel-worker"

    def test_calling_twice_installs_one_provider(self) -> None:
        """Three entrypoints each call setup; a second provider would silently swallow
        the spans sent to it."""
        assert tracing.setup_tracing(_settings(otel_enabled=True)) is not None
        assert tracing.setup_tracing(_settings(otel_enabled=True)) is None


def test_instrumenting_agents_is_safe_to_repeat() -> None:
    """Called on every setup, and agents are built on demand afterwards."""
    tracing.instrument_agents()
    tracing.instrument_agents()


class TestWhereSpansGo:
    """The endpoint and its credentials, which are silent when wrong: the exporter keeps
    batching and the UI simply stays empty."""

    def test_an_explicit_endpoint_wins_and_carries_no_credentials(self) -> None:
        endpoint, headers = tracing._otlp_target(
            _settings(
                otel_enabled=True,
                langfuse_public_key=SecretStr("pk-lf-1"),
                langfuse_secret_key=SecretStr("sk-lf-1"),
            )
        )
        assert endpoint == "http://localhost:4318/v1/traces"
        assert headers == {}

    def test_langfuse_is_the_fallback(self) -> None:
        endpoint, headers = tracing._otlp_target(
            Settings(
                otel_enabled=True,
                langfuse_public_key=SecretStr("pk-lf-1"),
                langfuse_secret_key=SecretStr("sk-lf-1"),
                langfuse_base_url="https://jp.cloud.langfuse.com/",
            )
        )
        assert endpoint == "https://jp.cloud.langfuse.com/api/public/otel/v1/traces"
        assert headers["Authorization"] == "Basic " + base64.b64encode(b"pk-lf-1:sk-lf-1").decode()

    def test_one_key_alone_is_refused(self) -> None:
        """A deployment that believes it is traced and is not."""
        with pytest.raises(ConfigError, match="LANGFUSE_PUBLIC_KEY"):
            tracing._otlp_target(
                Settings(otel_enabled=True, langfuse_public_key=SecretStr("pk-lf-1"))
            )


class TestWhatIsNotTraced:
    """A trace is one turn, and the page must not bury it.

    `web/src/run.ts` polls the chat endpoint every three seconds, so without this a
    two-minute run arrives as one real trace among forty empty ones — each an equal root
    in the UI, which is what makes the real one unfindable.
    """

    @staticmethod
    def _excluded(path: str) -> bool:
        from opentelemetry.util.http import parse_excluded_urls

        from mycel.api.app import UNTRACED

        return bool(parse_excluded_urls(UNTRACED).url_disabled(path))

    def test_the_poll_and_its_stream_are_dropped(self) -> None:
        job = "215bad5ee1da4121947bafe1c26414b0"
        assert self._excluded(f"/chat/{job}")
        assert self._excluded(f"/chat/{job}/events")

    def test_asking_a_question_is_still_the_root_of_its_trace(self) -> None:
        """Drop this and the worker's run has no parent to hang off."""
        assert not self._excluded("/chat")

    def test_the_page_talking_to_itself_is_dropped(self) -> None:
        assert self._excluded("/auth/me")
        assert self._excluded("/health/live")
        assert self._excluded("/app/login")

    def test_real_work_is_kept(self) -> None:
        assert not self._excluded("/auth/login")
        assert not self._excluded("/conversations")
        assert not self._excluded("/dashboard/MYC")
