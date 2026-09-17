"""Tracing setup. No collector is involved: these check the switch and the wiring."""

import pytest

from mycel.core.config import Settings
from mycel.observability import tracing


@pytest.fixture(autouse=True)
def _reset() -> "object":
    tracing.reset_for_tests()
    yield
    tracing.reset_for_tests()


def _settings(**kw: object) -> Settings:
    return Settings(otel_exporter_otlp_endpoint="http://localhost:4317", **kw)  # type: ignore[arg-type]


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
