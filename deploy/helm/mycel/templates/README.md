# Templates

No real manifests written yet — this directory holds the place and records how the files will
be split.

```
api/         deployment.yaml  service.yaml  hpa.yaml  ingress.yaml
worker/      deployment.yaml  hpa.yaml          # HPA on Kafka lag (KEDA)
scheduler/   deployment.yaml                    # replicas: 1, Recreate
vllm/        deployment.yaml  service.yaml      # if .Values.vllm.enabled
stateful/    postgres.yaml  kafka.yaml  qdrant.yaml  minio.yaml
observability/ prometheus.yaml  loki.yaml  grafana.yaml
_helpers.tpl                                    # shared names and labels
hooks/migrate.yaml                              # pre-upgrade: alembic upgrade head
```

Every Deployment needs all three probes. Without readiness, the Service sends requests to pods
that are not ready; without liveness, a hung pod just sits there; without startup, a
slow-booting pod gets killed for no reason.
