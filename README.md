# Mycel

Hệ multi-agent tự động tổng hợp **báo cáo và dashboard** từ nhiều nguồn dữ liệu rời rạc.

Tên lấy từ *mycelium* — mạng sợi nấm ngầm kết nối cả khu rừng. Mycel cũng vậy: chạy nền, âm
thầm gom dữ liệu từ Slack, Gmail, Confluence..., xử lý qua nhiều tầng, rồi mới "trồi lên"
thành báo cáo cho người dùng.

## Luồng dữ liệu

```
Sources ──► raw ──► silver ──► gold ──► Agents ──► Báo cáo / Dashboard
(Slack,    (thô,    (chuẩn    (sẵn      (phân tích,
 Gmail,    nguyên   hoá,      sàng để   tổng hợp)
 ...)      bản)     làm sạch) dùng)
```

Cả 3 tầng đều nằm trong **PostgreSQL**, mỗi tầng là một schema riêng.

## Cấu trúc

```
src/mycel/
  core/        Config, logging, exception, kiểu dùng chung
  storage/     Kết nối Postgres, repository cho từng tầng
  sources/     Connector tới từng provider  -> raw
  pipeline/    raw -> silver -> gold
  agents/      Manager điều phối + worker + tools
  reports/     Sinh báo cáo, dashboard từ gold
  scheduler/   Lập lịch job (sync, transform, báo cáo)
  api/         HTTP API
  observability/  Log có cấu trúc, trace OTel, metrics Prometheus

config/        File cấu hình theo môi trường và theo nguồn
deploy/        Config hạ tầng: OTel Collector, dashboard Grafana
migrations/    Alembic migration
docs/          Tài liệu thiết kế
scripts/       Script vận hành một lần
tests/         Test
```

Chi tiết từng tầng: [docs/architecture.md](docs/architecture.md) ·
Sơ đồ trực quan: [docs/architecture.html](docs/architecture.html)

## Bắt đầu

```bash
cp .env.example .env      # điền DB và API key
docker compose up -d      # app + postgres + observability
```

| Dịch vụ | URL |
|---|---|
| API | http://localhost:8000 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

Chạy trực tiếp không qua Docker: `uv sync` rồi `uvicorn mycel.api.app:app --reload`.

## Trạng thái

Đang dựng khung. Chưa có connector nào hoạt động.
