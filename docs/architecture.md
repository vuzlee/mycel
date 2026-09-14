# Kiến trúc Mycel

> Bản trực quan có sơ đồ phân tầng: [architecture.html](architecture.html)

## Nguyên tắc

1. **Một chiều.** Dữ liệu chỉ chảy raw → silver → gold. Không tầng nào đọc ngược lên.
2. **Agent chỉ đọc gold.** Agent không bao giờ chạm raw/silver — gold là hợp đồng duy nhất.
3. **Thêm nguồn không sửa code cũ.** Một provider mới = một file trong `sources/`.
4. **Gọi model chỉ qua `llm/`.** Không module nào import thẳng SDK provider.
5. **Việc lâu thì vào hàng đợi.** API không chờ LLM chạy xong.
6. **Đổi prompt phải chạy eval.** Báo cáo kém đi không làm test đỏ.
7. **Route mỏng, service dày.** Bỏ hẳn `api/` mà `scheduler` vẫn sinh được báo cáo thì tầng đang đúng chỗ.
8. **Một image cho mọi môi trường.** Build một lần, tag theo commit SHA. Khác nhau chỉ ở biến môi trường.
9. **Tên module = việc nó làm.** Không viết tắt, không tầng trừu tượng thừa.

## Ba tầng dữ liệu

| Tầng | Schema | Chứa gì | Ai ghi |
|---|---|---|---|
| **raw** | `raw` | Payload nguyên bản từ provider, chưa đụng vào. Giữ để replay được. | `sources/` |
| **silver** | `silver` | Đã chuẩn hoá schema, khử trùng lặp, ép kiểu, gắn timestamp thống nhất. | `pipeline/` |
| **gold** | `gold` | Bảng đã tổng hợp theo nghiệp vụ, sẵn sàng cho truy vấn và báo cáo. | `pipeline/` |

Giữ raw nguyên bản là điều quan trọng nhất: khi logic transform sai, ta chạy lại từ raw
thay vì phải gọi lại provider.

## Các module

### `core/`
Config đọc từ env/file, logger, exception gốc, kiểu dữ liệu dùng chung. Không import
module nào khác trong `mycel` — đây là tầng đáy.

### `storage/`
Engine và session Postgres, repository cho từng tầng. Mọi câu SQL nằm ở đây, không rải
rác trong pipeline hay agent.

### `sources/`
Mỗi provider một module: `sources/slack.py`, `sources/gmail.py`... Cùng một interface:
nhận khoảng thời gian cần sync, trả về bản ghi thô, ghi xuống `raw`. Không xử lý,
không làm sạch — việc đó của pipeline.

Cấu hình riêng của từng nguồn (endpoint, scope, rate limit) nằm ở `config/sources/`.

### `pipeline/`
Các bước biến đổi. Mỗi bước là một hàm thuần: đọc từ tầng dưới, ghi lên tầng trên,
idempotent — chạy lại hai lần cho cùng kết quả.

`pipeline/checks/` kiểm tra sau mỗi bước: thiếu cột, null bất thường, số đếm lệch quá
ngưỡng. Fail thì dừng, không ghi lên tầng trên. Provider đổi schema mà không báo là
chuyện thường; không check thì gold hỏng lặng lẽ và agent tự tin báo cáo số sai.

### `llm/`
Cổng duy nhất tới mọi model. Không module nào import thẳng SDK provider — nhờ vậy đổi
model, thêm cache hay đặt trần chi phí chỉ sửa một chỗ.

| File | Việc |
|---|---|
| `router.py` | Chọn local hay cloud cho từng lượt gọi |
| `cache.py` | Prompt trùng thì trả kết quả cũ, không gọi lại |
| `budget.py` | Cộng dồn token theo job, vượt trần thì raise thay vì gọi tiếp |

Ranh giới local/cloud:

- **local** — việc khối lượng lớn, đầu ra ngắn, hoặc dữ liệu nhạy cảm không muốn rời máy:
  phân loại, trích entity, chấm điểm liên quan, tóm tắt từng bản ghi.
- **cloud** — suy luận cuối: tổng hợp nhiều nguồn, viết báo cáo, quyết định cần ngữ cảnh dài.

Model 3B không đủ chất lượng viết báo cáo, nên nó gánh phần số lượng chứ không gánh phần
kết luận. Ràng buộc phần cứng cụ thể: `deploy/inference/README.md`.

### `agents/`
- **manager** — nhận yêu cầu báo cáo, chia nhỏ thành task, giao cho worker, ghép kết quả.
- **worker** — agent chuyên một việc (phân tích số liệu, viết tóm tắt, đối chiếu nguồn).
- **tools/** — năng lực agent gọi được: truy vấn gold, tính toán, dựng biểu đồ.
- **prompts/** — prompt tách khỏi code, sửa không cần deploy lại, và diff được khi eval tụt điểm.

Agent trả về output có cấu trúc và được validate; model trả sai format thì retry, không
để dữ liệu hỏng đi tiếp.

### `jobs/`
`scheduler/` trả lời *khi nào chạy*; `jobs/` trả lời *chạy cái gì, lỗi thì sao*. Sinh một
báo cáo mất vài phút và sẽ có lúc fail giữa chừng, nên:

- API đẩy việc vào hàng đợi rồi trả `job_id` ngay, không bắt client chờ.
- Mỗi job có idempotency key — chạy lại không sinh hai báo cáo trùng.
- Lỗi thì retry; hết lượt thì vào dead-letter để xem lại, không mất âm thầm.

### `reports/`
Từ kết quả agent dựng ra artifact cuối: báo cáo văn bản, bảng số liệu, dashboard.

### `services/`
Một file = một nghiệp vụ đầu-cuối. `report_service.py`, `sync_service.py`...

Tầng này tồn tại vì mỗi nghiệp vụ có ít nhất hai nơi gọi: `api/` (người bấm nút) và
`scheduler/` (tới giờ). Không có nó thì logic bị chép đôi và hai đường dần lệch nhau.

Service *điều phối*: kiểm quyền, đẩy job vào hàng đợi, trả `job_id`. Luật nghiệp vụ thật
nằm ở `pipeline/`, `agents/`, `reports/` — service không tự viết lại chúng.

### `scheduler/`
Trả lời *khi nào chạy*: sync nguồn theo giờ, transform sau khi sync xong, báo cáo hàng
ngày/tuần. Gọi thẳng `services/` đúng như `api/` gọi — không tự gọi HTTP vào chính mình.

### `api/`
Vỏ HTTP, không chứa nghiệp vụ.

| Thư mục | Việc |
|---|---|
| `routes/` | Nhận request, validate, gọi service, trả response. Không SQL, không gọi LLM, không `if/else` nghiệp vụ |
| `schemas/` | Hình dạng dữ liệu vào/ra qua HTTP. Khác bảng DB — đổi DB không vỡ API |

Có xác thực — dữ liệu bên trong là Slack và Gmail nội bộ.

`routes/health.py` tách hai loại: `/health/live` cho policy restart container,
`/health/ready` cho load balancer (DB tới được, migration đã chạy).

### Một request đi qua bốn tầng

| Tầng | Ai | Được làm gì |
|---|---|---|
| Vỏ | `api/routes/` | Nhận · validate · gọi service · trả |
| Nghiệp vụ | `services/` | Điều phối đầu-cuối. Tầng duy nhất cả `api/` lẫn `scheduler/` cùng gọi |
| Miền | `pipeline/` `agents/` `reports/` | Luật nghiệp vụ thật |
| Dữ liệu | `storage/` | Mọi câu SQL |

Quy tắc kiểm tra nhanh: bỏ hẳn `api/` đi mà `scheduler` vẫn sinh được báo cáo, thì các
tầng đang nằm đúng chỗ.

### `observability/`
Log có cấu trúc, trace OpenTelemetry, metrics Prometheus. Đây là module duy nhất cắt
ngang mọi tầng, nên phải giữ thật mỏng và không chứa logic nghiệp vụ.

Mỗi lần sync nguồn, mỗi bước transform, mỗi lượt gọi LLM đều là một span — khi báo cáo
sai số hoặc chạy chậm, ta lần ngược được về đúng bước gây ra.

## Thứ tự phụ thuộc

```
core ◄── storage ◄── sources
             ▲   ◄── pipeline
             │
             └──────► agents ◄── llm
                        ▲  ▲
                 reports┘  └ jobs, services, scheduler, api
```

Mũi tên là "được import bởi". `core` không phụ thuộc gì; `api` và `scheduler` ngồi trên cùng.
`observability` là ngoại lệ có chủ đích: mọi tầng đều import nó.

## Vận hành

`docker compose up` dựng cả app lẫn tầng quan trắc:

| Service | Vai trò |
|---|---|
| `api` | Cổng vào — nhận yêu cầu báo cáo, health check |
| `scheduler` | Chạy nền — sync, transform, báo cáo định kỳ |
| `postgres` | Một database, ba schema. Volume tách rời để nâng image không mất dữ liệu |
| `otel-collector` | Điểm gom duy nhất; chia trace về Tempo, metrics về Prometheus |
| `tempo` | Lưu trace — một yêu cầu báo cáo là một trace, từ HTTP tới từng lượt gọi LLM |
| `prometheus` | Lưu metrics — độ trễ sync, số bản ghi mỗi tầng, token đã dùng, tỷ lệ job lỗi |
| `worker` | Rút job ra chạy. Scale ngang bằng `--scale worker=N` |
| `vllm` | Model local, tuỳ chọn — bật bằng `--profile local-llm` |
| `grafana` | Dashboard, provision từ `deploy/grafana/` nên versioned theo code |

App chỉ gửi OTLP tới một địa chỉ (`otel-collector:4317`); đổi backend quan trắc về sau
chỉ cần sửa `deploy/otel/config.yaml`, không đụng code.

## Từ máy dev tới host

CI build image **một lần**, tag bằng commit SHA. Staging và prod kéo đúng image đó về
chạy — không build lại, nên không có chuyện "máy tôi chạy được".

```
git push ──► CI (lint · kiểu · migration · test) ──► build image (tag = SHA)
                     └─ eval chỉ chạy khi đụng prompt/ hoặc llm/
                                                          │
                                         registry ◄───────┘
                                            ├──► staging  (dữ liệu ẩn danh)
                                            └──► prod
```

Thứ tự deploy không đổi:

```bash
docker compose pull            # lấy image theo SHA
alembic upgrade head           # migration chạy trước code mới
docker compose up -d           # rồi mới đổi container
```

Migration chạy trước container mới, nên mọi thay đổi schema phải để code cũ vẫn chạy
được: muốn xoá cột thì làm hai lần release — lần đầu bỏ code dùng nó, lần sau mới drop.

Rollback = trỏ về tag SHA cũ. Chi tiết biến môi trường và secret: `deploy/envs/README.md`.

## Mở rộng sau này

Khi một module phình to thì tách thành thư mục, giữ nguyên tên:
`sources/slack.py` → `sources/slack/{client.py,parser.py}`. Không cần dựng sẵn tầng
`domain/application/infrastructure` khi chưa có gì để bỏ vào.

## Chất lượng báo cáo

Test bắt lỗi code. Báo cáo kém đi không làm test đỏ — output vẫn đúng format, chỉ là tệ
hơn. Đó là việc của `evals/`: golden set các cặp *dữ liệu gold → báo cáo con người chấp
nhận được*. Đổi prompt, đổi model, nâng version agent đều phải chạy lại và so điểm với
lần trước. Điểm tụt là chặn merge.
