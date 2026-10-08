"""OpenTelemetry setup: OTLP/HTTP export to Langfuse or an explicit endpoint.

Prompt and reply content is captured only when `OTEL_CAPTURE_CONTENT` is set.
"""

import base64
from typing import TYPE_CHECKING

from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import ConfigError
from mycel.core.logging import get_logger

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

log = get_logger(__name__)

_configured = False


def setup_tracing(settings: Settings | None = None) -> "TracerProvider | None":
    """Install the global TracerProvider once; return it, or `None` if disabled or already set."""
    global _configured

    cfg = settings or get_settings()
    if not cfg.otel_enabled:
        return None
    if _configured:
        return None

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint, headers = _otlp_target(cfg)

    resource = Resource.create(
        {"service.name": cfg.otel_service_name, "deployment.environment": cfg.mycel_env}
    )
    provider = TracerProvider(resource=resource)
    # Batched so export never blocks the request being traced.
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
    )
    trace.set_tracer_provider(provider)

    instrument_agents(cfg.otel_capture_content)
    _configured = True
    log.info(
        "tracing enabled",
        extra={
            "otel_endpoint": endpoint,
            "service_name": cfg.otel_service_name,
            "capture_content": cfg.otel_capture_content,
        },
    )
    return provider


def _otlp_target(cfg: Settings) -> tuple[str, dict[str, str]]:
    """An explicit endpoint without auth, else Langfuse with both keys required."""
    if cfg.otel_exporter_otlp_endpoint:
        return cfg.otel_exporter_otlp_endpoint, {}

    if cfg.langfuse_public_key is None or cfg.langfuse_secret_key is None:
        raise ConfigError(
            "OTEL_ENABLED is on with no endpoint, so traces go to Langfuse, but "
            "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are not both set"
        )

    pair = (
        f"{cfg.langfuse_public_key.get_secret_value()}:{cfg.langfuse_secret_key.get_secret_value()}"
    )
    token = base64.b64encode(pair.encode()).decode()
    endpoint = f"{cfg.langfuse_base_url.rstrip('/')}/api/public/otel/v1/traces"
    return endpoint, {"Authorization": f"Basic {token}"}


def instrument_agents(capture_content: bool = False) -> None:
    """Instrument every agent into the global provider; call after `set_tracer_provider`."""
    from pydantic_ai import Agent
    from pydantic_ai.models.instrumented import InstrumentationSettings

    Agent.instrument_all(
        InstrumentationSettings(include_content=capture_content, include_binary_content=False)
    )
