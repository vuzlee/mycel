"""Logging có cấu trúc, trace OpenTelemetry, metrics Prometheus.

  tracing.py     dựng OTel + xuất OTLP, một lần lúc khởi động
  llm_trace.py   thuộc tính LLM trên span (Langfuse đọc được)
  logging.py     log JSON kèm job_id, trace_id — in ra stdout, Promtail gom về Loki
  metrics.py     counter, histogram cho Prometheus

Ba tín hiệu, ba câu hỏi khác nhau — cần cả ba:

    metrics (Prometheus)  có đang hỏng không   độ trễ vọt lên, tỷ lệ job lỗi tăng
    trace   (Tempo)       hỏng ở đâu           chậm ở lượt gọi model nào
    log     (Loki)        hỏng vì sao          stack trace, payload provider trả về

Nối được ba cái là nhờ `trace_id` có mặt ở cả ba. Grafana đi từ metric vọt → trace
chậm nhất → đúng những dòng log của trace đó.

Không có gì ở đây biết HTTP là gì — phần dính HTTP nằm ở `api/`: `app.py` gọi
`tracing.setup()` rồi để `FastAPIInstrumentor` lo span cho từng request. Nhờ vậy
`scheduler`, `queue` và `etl` import được module này mà không kéo theo tầng web.

App chỉ gửi OTLP tới một địa chỉ (`otel-collector:4317`); collector chia trace về
Tempo, metrics về Prometheus. Đổi backend thì sửa `deploy/otel/collector.yaml`.
"""
