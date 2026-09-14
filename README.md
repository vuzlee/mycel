# Mycel

Hệ multi-agent tự động tổng hợp **báo cáo và dashboard** từ nhiều nguồn dữ liệu rời rạc
— Slack, Gmail, Confluence.

Tên lấy từ *mycelium*, mạng sợi nấm ngầm kết nối cả khu rừng. Mycel cũng vậy: chạy nền,
âm thầm gom dữ liệu, xử lý qua nhiều tầng, rồi mới "trồi lên" thành báo cáo.

> **Trạng thái:** đang dựng khung. Chưa có connector nào chạy thật.

## Nó làm gì

```
Slack · Gmail · … ──► raw ──► silver ──► gold ──► Agents ──► Báo cáo / Dashboard
                      thô     sạch      sẵn dùng
```

Ba tầng đều nằm trong một **PostgreSQL**, mỗi tầng một schema. Agent chỉ đọc `gold`.

Phần suy luận đi qua `llm/` — việc khối lượng lớn chạy model local, suy luận cuối gọi
model cloud. Không module nào import thẳng SDK provider.

## Chạy thử

```bash
cp .env.example .env      # điền DB và API key
docker compose up -d      # app + postgres + observability
```

| Dịch vụ | URL |
|---|---|
| API | http://localhost:8000 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

Không qua Docker: `uv sync` rồi `uvicorn mycel.api.app:app --reload`.
Muốn bật model local (cần GPU): thêm `--profile local-llm`.

## Cây thư mục

```
src/mycel/     Mã nguồn — xem docs/ để biết tầng nào làm gì
config/        Cấu hình theo môi trường và theo nguồn (bí mật ở .env)
deploy/        Config hạ tầng: OTel, Grafana, vLLM, môi trường deploy
evals/         Golden set chấm chất lượng báo cáo
migrations/    Alembic migration
docs/          Tài liệu thiết kế
tests/         Test
```

## Tài liệu

| | |
|---|---|
| **[docs/architecture.html](docs/architecture.html)** | Bản đầy đủ có sơ đồ — đọc cái này trước |
| [docs/architecture.md](docs/architecture.md) | Cùng nội dung, bản chữ |
| [deploy/inference/](deploy/inference/README.md) | Ràng buộc phần cứng cho model local |
| [deploy/envs/](deploy/envs/README.md) | Biến môi trường và cách lên staging/prod |
| [evals/](evals/README.md) | Đổi prompt hay đổi model thì chạy lại trước khi merge |
