"""Set up OpenTelemetry once at startup, exporting OTLP to `otel-collector`.

Handles only the transport-agnostic part: TracerProvider, exporter, resource attributes.
Spans for HTTP requests are `FastAPIInstrumentor`'s job — not hand-written, because the
semantic conventions (`http.route`, `http.status_code`, how streaming responses are
handled) are already standardised.

The backend is not in the code: the app knows one OTLP address, and
`deploy/otel/collector.yaml` decides whether traces flow to Tempo, Langfuse or elsewhere.
Changing backend does not require rebuilding the image.

Can be disabled entirely via env — development runs the app without standing up a collector.

Called from `api/app.py` at startup, and from the `scheduler` and `queue` entrypoints — all
three need traces, only `api` has HTTP.
"""

from typing import TYPE_CHECKING

from mycel.core.config import Settings, get_settings
from mycel.core.logging import get_logger

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

log = get_logger(__name__)

_configured = False


def setup_tracing(settings: Settings | None = None) -> "TracerProvider | None":
    """Install the global TracerProvider, or do nothing if OTel is off.

    Returns the provider so tests and entrypoints can flush it; `None` when disabled.

    **Idempotent on purpose.** The three entrypoints (`api`, `scheduler`, `queue`) each
    call this, and a process that runs more than one would otherwise install a second
    provider — which OpenTelemetry ignores with a warning, so the second set of spans
    quietly goes nowhere.
    """
    global _configured

    cfg = settings or get_settings()
    if not cfg.otel_enabled:
        return None
    if _configured:
        return None

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {"service.name": cfg.otel_service_name, "deployment.environment": cfg.mycel_env}
    )
    provider = TracerProvider(resource=resource)
    # Batched, not simple: a span export that blocks the request it is describing turns
    # observability into a latency source.
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=cfg.otel_exporter_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)

    instrument_agents()
    _configured = True
    log.info(
        "tracing enabled",
        extra={
            "otel_endpoint": cfg.otel_exporter_otlp_endpoint,
            "service_name": cfg.otel_service_name,
        },
    )
    return provider


def instrument_agents() -> None:
    """Make every agent emit GenAI spans into whatever provider is installed.

    Global rather than per-agent: `registry.py` builds agents on demand, so opting each
    one in individually means a new agent is untraced until someone remembers. The
    default is traced.

    pydantic-ai writes into the *global* provider, so this must run after
    `set_tracer_provider` — which is why `setup_tracing` calls it rather than the caller.
    """
    from pydantic_ai import Agent

    Agent.instrument_all()


def reset_for_tests() -> None:
    """Forget that setup ran. Tests only — a process does not un-configure tracing."""
    global _configured
    _configured = False
