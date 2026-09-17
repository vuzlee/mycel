"""Structured logging, OpenTelemetry traces, Prometheus metrics.

  tracing.py     set up OTel + OTLP export, once at startup
  llm_trace.py   LLM attributes on spans (readable by Langfuse)
  logging.py     JSON logs carrying job_id, trace_id — printed to stdout, Promtail ships
                 them to Loki
  metrics.py     counters and histograms for Prometheus

Three signals, three different questions — all three are needed:

    metrics (Prometheus)  is something broken   latency spike, job failure rate climbing
    trace   (Tempo)       where is it broken    which model call is slow
    log     (Loki)        why is it broken      stack trace, provider payload

They join up because `trace_id` appears in all three. Grafana goes from a metric spike →
the slowest trace → exactly that trace's log lines.

Nothing here knows what HTTP is — the HTTP-specific part lives in `api/`: `app.py` calls
`tracing.setup()` and lets `FastAPIInstrumentor` handle per-request spans. That way
`scheduler`, `queue` and `etl` can import this module without pulling in the web layer.

The app only ships OTLP to one address (`otel-collector:4317`); the collector routes traces
to Tempo and metrics to Prometheus. Changing backend means editing
`deploy/otel/collector.yaml`.
"""
