# Template

Chưa viết manifest thật — thư mục này giữ chỗ và ghi lại cách chia file.

```
api/         deployment.yaml  service.yaml  hpa.yaml  ingress.yaml
worker/      deployment.yaml  hpa.yaml          # HPA theo Kafka lag (KEDA)
scheduler/   deployment.yaml                    # replicas: 1, Recreate
vllm/        deployment.yaml  service.yaml      # if .Values.vllm.enabled
stateful/    postgres.yaml  kafka.yaml  qdrant.yaml  minio.yaml
observability/ collector.yaml  tempo.yaml  prometheus.yaml  loki.yaml  grafana.yaml
_helpers.tpl                                    # tên, label dùng chung
hooks/migrate.yaml                              # pre-upgrade: alembic upgrade head
```

Mỗi Deployment phải có đủ ba probe. Thiếu readiness thì Service đẩy request vào
pod chưa sẵn sàng; thiếu liveness thì pod treo cứ nằm đó; thiếu startup thì pod
khởi động lâu bị giết oan.
