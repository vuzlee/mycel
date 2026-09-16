"""Dựng OpenTelemetry một lần lúc khởi động, xuất OTLP về `otel-collector`.

Chỉ lo phần không dính transport: TracerProvider, exporter, resource attribute. Span cho
HTTP request là việc của `FastAPIInstrumentor` — không tự viết, vì semantic convention
(`http.route`, `http.status_code`, cách xử lý streaming response) đã chuẩn hoá rồi.

Backend không nằm trong code: app chỉ biết một địa chỉ OTLP, `deploy/otel/collector.yaml`
quyết định trace chảy về Tempo, Langfuse hay chỗ khác. Đổi backend không phải build lại image.

Tắt được hoàn toàn bằng env — dev không cần dựng collector mới chạy được app.

Gọi từ `api/app.py` lúc khởi động, và từ entrypoint của `scheduler` với `queue` — cả ba
đều cần trace, chỉ mình `api` có HTTP.
"""
