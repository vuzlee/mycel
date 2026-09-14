# Mycel

Hệ multi-agent tự động tổng hợp **báo cáo và dashboard** từ nhiều nguồn dữ liệu rời rạc.

Tên lấy từ *mycelium* — mạng sợi nấm ngầm kết nối cả khu rừng. Mycel cũng vậy: chạy nền, âm
thầm gom dữ liệu từ Slack, Gmail, Confluence..., xử lý qua nhiều tầng, rồi mới "trồi lên"
thành báo cáo cho người dùng.

## Luồng dữ liệu

```
Sources ──► raw ──► silver ──► gold ──► Agents ──► Báo cáo / Dashboard
(Slack,    (thô,    (chuẩn    (sẵn      (qua llm/:
 Gmail,    nguyên   hoá,      sàng để    local hoặc
 ...)      bản)     làm sạch) dùng)      cloud)
```

Cả 3 tầng đều nằm trong **PostgreSQL**, mỗi tầng là một schema riêng.
Agent chỉ đọc `gold` — không bao giờ chạm `raw` hay `silver`.

## Tầng AI

Mọi lượt gọi model đi qua `llm/`, không module nào import thẳng SDK provider:

| | Dùng khi | Chạy ở |
|---|---|---|
| **local** | Việc khối lượng lớn, đầu ra ngắn, dữ liệu nhạy cảm — phân loại, trích entity, chấm điểm, tóm tắt từng bản ghi | vLLM + Qwen 2.5 3B AWQ |
| **cloud** | Suy luận cuối — tổng hợp nhiều nguồn, viết báo cáo | API model lớn |

Không bật container vLLM thì mọi lượt gọi đi cloud; code không đổi vì cả hai đều là
endpoint OpenAI-compatible. Chi tiết ràng buộc phần cứng: [deploy/inference/](deploy/inference/README.md)

## Cấu trúc

```
src/mycel/
  core/        Config, logging, exception, kiểu dùng chung
  storage/     Kết nối Postgres, repository cho từng tầng
  sources/     Connector tới từng provider  -> raw
  pipeline/    raw -> silver -> gold
  llm/         Cổng duy nhất tới model: router, cache, budget
  agents/      Manager điều phối + worker + tools + prompts
  jobs/        Hàng đợi: chạy nền, retry, dead-letter
  reports/     Sinh báo cáo, dashboard từ gold
  scheduler/   Tới giờ thì đẩy việc vào hàng đợi
  api/         HTTP API
  observability/  Log có cấu trúc, trace OTel, metrics Prometheus

config/        File cấu hình theo môi trường và theo nguồn
deploy/        Config hạ tầng: OTel, Grafana, vLLM
evals/         Golden set chấm chất lượng báo cáo
migrations/    Alembic migration
docs/          Tài liệu thiết kế
scripts/       Script vận hành một lần
tests/         Test code
```

Chi tiết từng tầng: [docs/architecture.md](docs/architecture.md) ·
Sơ đồ trực quan: [docs/architecture.html](docs/architecture.html)

## Bắt đầu

```bash
cp .env.example .env      # điền DB và API key
docker compose up -d      # app + postgres + observability

# Muốn chạy model 3B ngay trên máy (cần GPU):
docker compose --profile local-llm up -d
```

| Dịch vụ | URL |
|---|---|
| API | http://localhost:8000 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

Chạy trực tiếp không qua Docker: `uv sync` rồi `uvicorn mycel.api.app:app --reload`.

Đổi prompt hay đổi model thì chạy lại golden set trước khi merge — xem [evals/](evals/README.md).

## Trạng thái

Đang dựng khung. Chưa có connector nào hoạt động.
