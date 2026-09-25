"""Set up OpenTelemetry once at startup, exporting agent runs to Langfuse.

**Two backends, one protocol.** Langfuse is the one that gets read: it renders a run as a
tree of model and tool calls with their prompts, tokens and cost. The Grafana stack behind
the `monitoring` profile answers different questions — metrics over time, logs across
machines — and speaks the same OTLP. Which one receives a span is `OTEL_EXPORTER_OTLP_
ENDPOINT` and nothing else; leave it unset and Langfuse's own endpoint is derived from its
base url, so a deployment sets two keys and stops thinking about it.

**HTTP/protobuf, not gRPC.** Langfuse Cloud accepts OTLP over HTTP only. The endpoint is
a full path (`/api/public/otel/v1/traces`), not a host, and authentication is Basic auth
over the project's key pair rather than a bearer token — both are unlike the collector
this module used to talk to, and both are silent when wrong: the exporter keeps batching
and the UI simply stays empty.

**Span content is opt-in here, though the library opts in for you.** pydantic-ai's
`InstrumentationSettings` defaults `include_content=True`, so a span carries the prompt
that was sent and the text that came back unless somebody says otherwise. That is the
right default for a library and the wrong one for this deployment: those two fields are
the question a user typed and the internal figures that answered it, and Langfuse Cloud
is a third party. `OTEL_CAPTURE_CONTENT` decides, and it is off unless set.

Turning it off costs nothing structural — model, tokens, cost and the shape of the call
tree are span attributes either way. What is lost is the ability to read *what* an agent
asked, which is exactly what makes it worth turning on in development.

**Secrets must not ride along with a prompt.** A refresh token, a password, a session
token: none of those belong in a span whether content is captured or not. They sit in the
same objects as the prompt, so the discipline is to keep them out of prompts in the first
place — a span captures faithfully and cannot tell the difference.

Can be disabled entirely via env — development runs without an exporter at all.

Called from `api/app.py` at startup, from the `scheduler` and `queue` entrypoints, and
from any script that wants its run in the UI.
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
    """Install the global TracerProvider, or do nothing if OTel is off.

    Returns the provider so callers can flush it before exiting; `None` when disabled or
    already configured.

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
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint, headers = _otlp_target(cfg)

    resource = Resource.create(
        {"service.name": cfg.otel_service_name, "deployment.environment": cfg.mycel_env}
    )
    provider = TracerProvider(resource=resource)
    # Batched, not simple: a span export that blocks the request it is describing turns
    # observability into a latency source.
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
    """Where spans go, and what proves we may send them.

    An explicit endpoint wins and carries no credentials — that is a collector on the
    local network, which authenticates by being unreachable from outside it. Otherwise
    spans go to Langfuse, whose keys must both be present: one alone is a deployment that
    believes it is traced and is not.
    """
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
    """Make every agent emit GenAI spans into whatever provider is installed.

    Global rather than per-agent: `registry.py` builds agents on demand, so opting each
    one in individually means a new agent is untraced until someone remembers. The
    default is traced.

    `capture_content` puts the prompt and the reply on the span. Off by default here,
    against the library's own default, for the reason in the module docstring.

    Binary content is never captured, regardless: an image or a PDF arrives base64-encoded
    in a span attribute, which is megabytes nobody reads through a trace viewer.

    pydantic-ai writes into the *global* provider, so this must run after
    `set_tracer_provider` — which is why `setup_tracing` calls it rather than the caller.
    """
    from pydantic_ai import Agent
    from pydantic_ai.models.instrumented import InstrumentationSettings

    Agent.instrument_all(
        InstrumentationSettings(include_content=capture_content, include_binary_content=False)
    )


def reset_for_tests() -> None:
    """Forget that setup ran. Tests only — a process does not un-configure tracing."""
    global _configured
    _configured = False
