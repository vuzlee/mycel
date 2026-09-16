# Kiến trúc Mycel

> Bản trực quan có sơ đồ phân tầng: [architecture.html](architecture.html)
> · Bảng theo dõi tech stack: [stack.html](stack.html)

## Nguyên tắc

1. **Một chiều.** Dữ liệu chỉ chảy raw → silver → gold. Không tầng nào đọc ngược lên.
2. **Agent chỉ đọc gold.** Agent không bao giờ chạm raw/silver — gold là hợp đồng duy nhất.
3. **Thêm nguồn không sửa code cũ.** Một provider mới = một file trong `sources/`.
4. **Gọi model chỉ qua `llm/`.** Không module nào import thẳng SDK provider.
5. **Việc lâu thì vào hàng đợi.** API không chờ LLM chạy xong.
6. **Đổi prompt phải chạy eval.** Báo cáo kém đi không làm test đỏ.
7. **Controller mỏng, pipeline dày.** Bỏ hẳn `api/` mà `scheduler` vẫn sinh được báo cáo thì tầng đang đúng chỗ.
8. **Một image cho mọi môi trường.** Build một lần, tag theo commit SHA. Khác nhau chỉ ở biến môi trường.
9. **Tên module = việc nó làm.** Không viết tắt, không tầng trừu tượng thừa.

## Ba tầng dữ liệu

| Tầng | Schema | Chứa gì | Ai ghi |
|---|---|---|---|
| **raw** | `raw` | Payload nguyên bản từ provider, chưa đụng vào. Giữ để replay được. | `sources/` |
| **silver** | `silver` | Đã chuẩn hoá schema, khử trùng lặp, ép kiểu, gắn timestamp thống nhất. | `etl/` |
| **gold** | `gold` | Bảng đã tổng hợp theo nghiệp vụ, sẵn sàng cho truy vấn và báo cáo. | `etl/` |

Giữ raw nguyên bản là điều quan trọng nhất: khi logic transform sai, ta chạy lại từ raw
thay vì phải gọi lại provider.

## Các module

### `core/`
Config đọc từ env/file, logger, exception gốc, kiểu dữ liệu dùng chung. Không import
module nào khác trong `mycel` — đây là tầng đáy.

`agents/core/` cùng khuôn nhưng hẹp hơn: nền chung của riêng `agents/`.

### `storage/`
Ba kho, ba loại dữ liệu khác nhau. Mọi truy cập đi qua đây.

| | Backend | Chứa gì |
|---|---|---|
| `postgres/` | PostgreSQL 16 | State giao dịch: ba tầng raw/silver/gold, job, quyền |
| `vectors/` | Qdrant | Embedding cho tìm kiếm knowledge base |
| `objects/` | MinIO (S3 API) | File lớn: PDF nguồn, báo cáo đã render |

Vì sao không nhét hết vào Postgres:

- **Vector.** `pgvector` chạy được, nhưng tới vài triệu vector thì index HNSW ăn RAM
  tranh với chính workload giao dịch trên cùng instance. Tách ra thì scale độc lập.
- **File.** Blob trong Postgres làm database phình, backup chậm, và mỗi lần đọc phải kéo
  cả file qua connection của pool. API trả presigned URL, file 200MB không đi qua process API.

Postgres giữ **metadata** của file (thuộc báo cáo nào, key trong bucket); bucket giữ
**nội dung**. Không bao giờ ngược lại.

Nguồn của embedding là **gold**, không phải raw — cùng hợp đồng mà agent đọc, nên kết quả
tìm kiếm và kết quả truy vấn bảng không mâu thuẫn nhau. Quyền xem truyền xuống thành
filter của Qdrant, không lọc sau khi đã lấy top-k: lấy 10 kết quả rồi mới bỏ cái không
được phép xem thì có khi còn 2.

Mọi câu SQL, mọi truy vấn vector, mọi thao tác file nằm ở đây, không rải rác trong
pipeline hay agent. Dùng S3 API nên chuyển sang S3 thật sau này chỉ là đổi endpoint.

### `sources/`
Mỗi provider một module: `sources/slack.py`, `sources/gmail.py`... Cùng một interface:
nhận khoảng thời gian cần sync, trả về bản ghi thô, ghi xuống `raw`. Không xử lý,
không làm sạch — việc đó của pipeline.

Cấu hình riêng của từng nguồn (endpoint, scope, rate limit) nằm ở `config/sources/`.

### `etl/`
Các bước biến đổi dữ liệu: raw → silver → gold. Đây là ETL chạy nền theo lịch, **không
phải** chuỗi xử lý request — chuỗi đó nằm ở `managers/<miền>/pipeline.py`.

Mỗi bước là một hàm thuần: đọc từ tầng dưới, ghi lên tầng trên, idempotent — chạy lại
hai lần cho cùng kết quả.

`etl/checks/` kiểm tra sau mỗi bước: thiếu cột, null bất thường, số đếm lệch quá
ngưỡng. Fail thì dừng, không ghi lên tầng trên. Provider đổi schema mà không báo là
chuyện thường; không check thì gold hỏng lặng lẽ và agent tự tin báo cáo số sai.

### `llm/`
Cổng duy nhất tới mọi model. Không module nào import thẳng SDK provider — nhờ vậy đổi
model, thêm cache hay đặt trần chi phí chỉ sửa một chỗ.

| File | Việc |
|---|---|
| `router.py` | Chọn local hay cloud cho từng lượt gọi |
| `client.py` | Nơi duy nhất import SDK provider — gọi model thật, trả kết quả hoặc luồng delta |
| `providers/` | Khác biệt riêng của từng provider: `local.py` (vLLM), `cloud.py` |
| `cache.py` | Prompt trùng thì trả kết quả cũ, không gọi lại |
| `tokens.py` | Đếm token *trước* khi gửi, để chặn trước chứ không phải sau khi đã trả tiền |
| `usage.py` | Đếm *sau* khi gọi: token, cache hit, thời gian. Một chỗ đếm, ba nơi dùng — budget, trace, log |
| `budget.py` | Cộng dồn token theo job, vượt trần thì raise thay vì gọi tiếp |

Ranh giới local/cloud:

- **local** — việc khối lượng lớn, đầu ra ngắn, hoặc dữ liệu nhạy cảm không muốn rời máy:
  phân loại, trích entity, chấm điểm liên quan, tóm tắt từng bản ghi.
- **cloud** — suy luận cuối: tổng hợp nhiều nguồn, viết báo cáo, quyết định cần ngữ cảnh dài.

Model 3B không đủ chất lượng viết báo cáo, nên nó gánh phần số lượng chứ không gánh phần
kết luận. Ràng buộc phần cứng cụ thể: `deploy/inference/README.md`.

### `agents/`
Tách hai tầng, vì chúng đổi với nhịp khác nhau: cách stream token hay cách gắn trace gần
như không đổi, còn prompt thì đổi liên tục.

**Khung — `agents/core/`**, nền chung của riêng `agents/`, không dính nghiệp vụ. Cùng
khuôn với `mycel/core/` nhưng hẹp hơn một tầng: hễ thấy `core/` lồng trong một package thì
hiểu là "nền chung của package đó".


| | Việc |
|---|---|
| `agent.py` | Vòng chạy: dựng message, gọi model, gọi tool, lặp tới khi có output. `run()` và `run_stream()` dùng chung vòng này |
| `config.py` · `model_builder.py` | Khai model dạng `'<tier>:<model_name>'`; builder dịch spec thành client đã gắn timeout và retry |
| `run_context.py` | Thứ một lượt chạy mang theo: `job_id`, budget, session DB, trace context |
| `schemas.py` | Hợp đồng nội bộ giữa agent, tool và streaming (khác `managers/*/schemas.py` là hợp đồng HTTP) |
| `hooks.py` | Chỗ duy nhất thấy mọi run — gắn trace, log usage, cộng budget |
| `guards.py` | Chặn vòng lặp vô hạn, model lặp chính nó, retry output sai schema |
| `streaming/` | Sự kiện thô từ model → sự kiện miền có tên: `reader` · `mapper` · `envelope` · `sink` · `output/` |
| `integrations/` | `mcp.py` gắn tool từ MCP server ngoài; `agent_protocol.py` để dành cho hệ thứ hai |

**Nghiệp vụ**, tầng trên:

- **`orchestrator.py`** — nhận yêu cầu báo cáo, chia task, giao việc, ghép kết quả. Không tự
  phân tích hay viết chữ. Không đặt tên `manager.py` để khỏi lẫn với `managers/` — cái kia
  là điểm vào HTTP theo miền.
- **`analyst.py` · `writer.py` · `reviewer.py`** — mỗi agent một việc: đọc số từ gold, viết
  văn bản từ số đó, đối chiếu bản nháp với nguồn. Chuyên một việc thì prompt ngắn, eval chấm
  được từng cái, hỏng cái nào biết ngay cái đó. Để phẳng cạnh `orchestrator.py`, không bọc
  thêm một tầng thư mục — khi nào một agent phình ra thì tách thành thư mục.
- **`registry.py`** — khai báo agent và tool orchestrator được dùng. Thêm agent = thêm một dòng.
- **`tools/`** — `query_gold` (qua `storage/postgres/`, chỉ đọc gold, có trần số dòng),
  `search_docs` (qua `storage/vectors/`), `chart`, `compute`. Hai cách tra cứu cho hai loại
  câu hỏi: `query_gold` trả lời câu có số liệu chính xác, `search_docs` trả lời câu mơ hồ.
  Nhầm chỗ thì agent đi tìm số bằng tìm kiếm ngữ nghĩa rồi bịa ra con số gần đúng.
- **`prompts/`** — prompt tách khỏi code, sửa không cần deploy lại, diff được khi eval tụt điểm.

Agent trả về output có cấu trúc và được validate; model trả sai format thì retry, không
để dữ liệu hỏng đi tiếp.

**Budget cộng ở hook, không cộng ở chỗ gọi model.** Usage của sub-agent không tự cộng lên
agent cha, nên nếu đếm ở call site thì agent con sẽ lọt sổ. `hooks.py` là chỗ duy nhất nhìn
thấy mọi run, kể cả run lồng nhau.

**Guard khác budget.** Budget đếm tiền của cả job; guard đếm hành vi của một lượt chạy.
Vòng lặp hỏng chạm guard trong vài giây, chạm budget thì đã tốn tiền rồi.

### `queue/`
Tầng job nằm **trên** Kafka, **không phải** bản thân broker — Kafka chạy ngoài, khai trong
`docker-compose` (KRaft mode, không cần Zookeeper). Đổi broker thì sửa ở đây, phần còn lại
của hệ thống không biết.

`scheduler/` trả lời *khi nào chạy*; `queue/` trả lời *chạy cái gì, lỗi thì sao*. Sinh một
báo cáo mất vài phút và sẽ có lúc fail giữa chừng, nên:

- API đẩy việc vào hàng đợi rồi trả `job_id` ngay, không bắt client chờ.
- Mỗi job có idempotency key — chạy lại không sinh hai báo cáo trùng.
- Lỗi thì retry; hết lượt thì vào dead-letter để xem lại, không mất âm thầm.

| File | Việc |
|---|---|
| `job.py` | Hình dạng một job: payload, idempotency key, số lần đã retry, trace context |
| `producer.py` | Đẩy job vào topic: chọn partition theo key, `acks=all`, inject trace context |
| `consumer.py` | Rút job ra chạy, commit sau khi xong |
| `retry.py` | Topic retry theo bậc và dead-letter |
| `context.py` | Mang trace context qua ranh giới process — xem mục `observability/` |

**Bốn thứ Kafka không cho sẵn, phải tự làm.** Kafka là log có thứ tự, không phải hàng đợi
task — nên:

| | Vì sao | Cách làm |
|---|---|---|
| Retry không theo từng job | Kafka commit theo offset; `seek` lùi lại thì chặn cả partition | Đẩy sang topic retry rồi commit đi tiếp: `jobs` → `jobs.retry.1m` → `jobs.retry.10m` → `jobs.dlq` |
| Kafka không đếm số lần retry | Không có khái niệm "lần thử" | Đếm trong header của message |
| Không có message hẹn giờ | Kafka không delay | Consumer của topic retry ngủ tới khi message đủ tuổi |
| Job dài bị coi là chết | `max.poll.interval.ms` mặc định 5 phút, báo cáo mất vài phút | Nâng lên (`KAFKA_MAX_POLL_INTERVAL_MS`); quá hạn thì rebalance và job chạy lại từ đầu |

**Số partition là trần của song song, không phải số worker.** Topic 6 partition thì worker
thứ 7 ngồi không — kể cả khi HPA đã dựng đủ pod. Partition tăng được nhưng không giảm, và
tăng thì phá thứ tự theo key.

**Commit sau khi xong, không commit lúc nhận.** Worker chết giữa job thì job được giao lại —
đúng mong muốn, nhưng thành at-least-once, nên idempotency key ở `job.py` là **bắt buộc**
chứ không phải tuỳ chọn. Key đó phải suy ra từ nội dung việc (miền + khoảng thời gian +
tham số), không phải UUID sinh mới mỗi lần.

Bù lại Kafka cho hai thứ broker thường không có: log replay được, và thêm consumer group
mới đọc lại cùng dòng dữ liệu mà không ảnh hưởng group đang chạy.

Trace context nằm trong **header** của message, không nằm trong payload, nên nó theo job
sang cả topic retry và dead-letter — job vào DLQ vẫn mở lại được trace về đúng lúc bấm nút.

### `reports/`
Từ kết quả agent dựng ra artifact cuối: báo cáo văn bản, bảng số liệu, dashboard.

### `managers/`
Điểm vào của hệ thống, **chia theo miền nghiệp vụ**. HTTP không gọi thẳng service — nó
gọi vào manager của miền tương ứng:

```
managers/report/          mọi thứ liên quan tới báo cáo
  controller.py           endpoint HTTP — nhận, validate, gọi pipeline, trả
  pipeline.py             chuỗi nghiệp vụ — gọi lần lượt các service
  schemas.py              hình dạng dữ liệu vào/ra qua HTTP
managers/sync/            miền đồng bộ nguồn, cùng ba file đó
```

Thêm một miền mới = thêm một thư mục ở đây + một dòng `include_router` trong
`api/app.py`. Không đụng miền đang có.

Vì sao chia theo miền chứ không theo kỹ thuật: sửa một nghiệp vụ thì mở đúng một thư
mục, không phải nhảy giữa `routes/`, `services/` và `pipeline/` nằm ở ba nơi.

**Pipeline là chuỗi, service là mắt xích.** `managers/report/pipeline.py` định nghĩa
*thứ tự*: `permission` → `enqueue` → *(worker rút job ra chạy)* → `gather` → `analyze` →
`render`. `managers/sync/pipeline.py`: `fetch` → `transform` → `check`. Pipeline không
tự làm việc gì, chỉ ghép service lại.

### `services/`
Một file = một việc đơn lẻ, làm xong một chuyện: `permission.py`, `enqueue.py`,
`fetch.py`, `transform.py`, `gather.py`, `analyze.py`, `render.py`, `check.py`.

Tên file là động từ, không mang hậu tố `_service` — đã nằm trong `services/` rồi.

Service phải dùng lại được — `gather.py` phục vụ cả miền báo cáo lẫn miền đồng bộ.
Nó không biết mình đang nằm trong chuỗi nào, cũng không biết ai gọi nó: HTTP hay
scheduler đều như nhau.

Luật nghiệp vụ phức tạp (transform, suy luận, dựng artifact) nằm ở `etl/`, `agents/`,
`reports/` — service chỉ gọi tới.

### `scheduler/`
Trả lời *khi nào chạy*: sync nguồn theo giờ, transform sau khi sync xong, báo cáo hàng
ngày/tuần. Gọi thẳng `pipeline` trong `managers/` — đúng chỗ controller gọi, chỉ bỏ qua
mắt xích HTTP. Không tự gọi HTTP vào chính mình.

### `api/`
Vỏ HTTP, mỏng nhất có thể. Endpoint nghiệp vụ **không** nằm ở đây — chúng nằm trong
`managers/<miền>/controller.py`.

| File | Việc |
|---|---|
| `app.py` | Nơi ráp: tạo app, gắn controller của từng manager, middleware, observability. `uvicorn mycel.api.app:app` trỏ vào đây |
| `middleware.py` | Chỉ `request_id` — phần còn lại dùng đồ có sẵn |
| `dependencies.py` | Thứ controller khai qua `Depends()`: xác thực, session DB, phân trang |
| `health.py` | `/health/live` cho policy restart container, `/health/ready` cho load balancer (DB tới được, migration đã chạy). Không thuộc miền nghiệp vụ nào |

`app.py` là file duy nhất biết hệ thống có những miền nào.

**Chỉ tự viết một middleware.** Phần lớn thứ hay bị viết tay đều đã có sẵn, và tự viết
là bảo trì lại thứ đã chuẩn hoá:

| Việc | Dùng gì |
|---|---|
| Span cho mỗi request | `FastAPIInstrumentor.instrument_app(app)` — đúng semantic convention của OTel |
| CORS | `CORSMiddleware` của Starlette |
| Một hình dạng lỗi | `@app.exception_handler(...)` — cơ chế riêng của FastAPI, không phải middleware |
| Rate limit | Nginx/ingress chặn trước khi chạm app; cần theo user thì `slowapi` |
| Xác thực | `Depends()` — xem bên dưới |
| **`request_id`** | **Tự viết** |

`request_id` tự viết vì phần giá trị là đặt id vào `contextvars` (built-in của Python, không
phải của FastAPI) để `observability/logging.py` tự đọc — controller khỏi phải viết
`log.info(..., request_id=rid)` ở từng dòng. Logger là của mình nên không thư viện nào làm
hộ đoạn đó.

**Viết dạng pure ASGI, đừng dùng `BaseHTTPMiddleware`.** Cái đó buffer response nên làm
nghẽn SSE — mà `agents/core/streaming/` sinh ra chính là để stream. Lỗi này không báo gì,
chỉ là token về thành một cục ở cuối.

**Xác thực là `Depends()`, không phải middleware.** Ba lý do cụ thể: middleware chạy cho
mọi route nên phải tự duy trì danh sách loại trừ `/health` và `/docs`; dependency vào được
OpenAPI schema nên `/docs` hiện ổ khoá; và controller nhận thẳng
`user: User = Depends(current_user)` có kiểu, mypy strict kiểm được — middleware chỉ nhét
vào `request.state`, mypy không thấy gì.

Có xác thực — dữ liệu bên trong là Slack và Gmail nội bộ. Nó chỉ trả lời *anh là ai*; còn
*anh được xem báo cáo nào* là việc của `services/permission.py`, vì nó cần ngữ cảnh nghiệp
vụ mà tầng HTTP không có.

### Một request đi qua các tầng

| Tầng | Ai | Được làm gì |
|---|---|---|
| Vỏ | `api/app.py` | Tạo app, gắn controller, middleware, observability. Không endpoint, không nghiệp vụ |
| Điểm vào | `managers/*/controller.py` | Nhận · validate · gọi pipeline · trả |
| Chuỗi | `managers/*/pipeline.py` | Định nghĩa thứ tự các bước. Tầng duy nhất cả `api/` lẫn `scheduler/` cùng gọi |
| Mắt xích | `services/` | Một việc đơn lẻ, dùng lại được ở nhiều pipeline |
| Miền | `etl/` `agents/` `reports/` | Luật nghiệp vụ thật |
| Dữ liệu | `storage/` | Mọi câu SQL |

Quy tắc kiểm tra nhanh: bỏ hẳn `api/` đi mà `scheduler` vẫn sinh được báo cáo, thì các
tầng đang nằm đúng chỗ.

**Hai trục, đừng lẫn.** Trục dữ liệu `sources → raw → etl → silver → gold` chạy nền
theo lịch, tính bằng phút. Trục request `controller → pipeline → service` chạy khi
người dùng bấm nút, tính bằng giây. Hai trục gặp nhau đúng một chỗ: ở `gold`.

### `observability/`
Module duy nhất cắt ngang mọi tầng, nên phải giữ thật mỏng và không chứa logic nghiệp vụ.

| File | Việc |
|---|---|
| `tracing.py` | Dựng OTel một lần lúc khởi động, xuất OTLP. Chỉ lo phần không dính transport — span cho HTTP là việc của `FastAPIInstrumentor`. Tắt được bằng env |
| `llm_trace.py` | Thuộc tính riêng của LLM trên span theo quy ước Langfuse đọc được: model, input, output, token, chi phí |
| `logging.py` | Log JSON, mỗi dòng kèm `trace_id` · `request_id` · `job_id`. In ra stdout, Promtail gom về Loki |
| `metrics.py` | Độ trễ sync, số bản ghi mỗi tầng, token đã dùng, tỷ lệ job lỗi |

**Ba tín hiệu, ba câu hỏi khác nhau** — cần cả ba, không cái nào thay được cái nào:

| | Backend | Trả lời |
|---|---|---|
| Metrics | Prometheus | *Có đang hỏng không* — độ trễ vọt lên, tỷ lệ job lỗi tăng |
| Trace | Tempo | *Hỏng ở đâu* — chậm ở lượt gọi model nào, ở service nào trong năm service |
| Log | Loki | *Hỏng vì sao* — stack trace, payload provider trả về |

Nối được ba cái là nhờ `trace_id` có mặt ở cả ba: từ metric vọt bấm sang trace chậm nhất,
từ span bấm sang đúng những dòng log của trace đó. Grafana provision hai chiều đó trong
`deploy/grafana/datasources/`.

`trace_id` nằm trong **nội dung** dòng log JSON, không phải label của Loki — label có bao
nhiêu giá trị khác nhau thì Loki tạo bấy nhiêu stream, mà `trace_id` gần như không lặp lại.
Grafana bắt bằng derived field.

App chỉ **in log ra stdout**, không tự gửi đi đâu: Promtail gom stdout của container rồi
đẩy sang Loki, và trong K8s cũng đúng cơ chế đó. Nhờ vậy không module nào biết Loki tồn tại.

Không có gì ở đây biết HTTP là gì — phần dính HTTP nằm ở `api/`, và `api/app.py` gọi
`tracing.setup()` rồi để `FastAPIInstrumentor` lo span cho request. Nhờ vậy `scheduler`,
`queue` và `etl` import được module này mà không kéo theo tầng web.

**Ba id, ba nguồn khác nhau** — chỗ này hay nhầm:

| | Ai sinh | Dùng để |
|---|---|---|
| `trace_id` | OTel tự, sau khi instrument. Đọc từ span hiện tại | Nối log ↔ trace |
| `request_id` | Mình, ở `api/middleware.py` | Trả cho client — người báo lỗi đưa đúng id này |
| `job_id` | Mình, khi đẩy vào `queue/` | Nối request với việc chạy nền sau đó |

Logger **không** tự biết `trace_id`: mỗi lần log phải đọc span hiện tại rồi gắn vào. Đó là
đoạn nối duy nhất phải viết tay, và cũng là thứ khiến từ một dòng log nhảy thẳng sang trace
tương ứng được.

Một yêu cầu báo cáo là một cây span: HTTP → pipeline → queue → worker → orchestrator → từng
agent → từng lượt gọi model. Báo cáo sai số hoặc chạy chậm thì lần ngược được về đúng lượt
gọi gây ra.

**Chỗ trace dễ đứt nhất là hàng đợi.** Worker là process khác, `contextvars` không vượt qua
ranh giới process, nên trace context **không** tự đi theo job. Không làm gì thì Grafana hiện
hai trace rời nhau — một cái HTTP kết thúc ở chữ "đã nhận", một cái báo cáo mọc lên từ hư
không. Không lỗi nào báo cả.

Cách nối: `queue/context.py` inject trace context vào **header** của message lúc enqueue,
extract lúc worker nhận, dùng chuẩn W3C `traceparent` của OTel — cùng chuẩn với header HTTP.
Phải làm tay ở cả hai đầu; quên một đầu thì không lỗi nào báo, chỉ là hai cây trace rời nhau.

Chỗ gọi vào `llm_trace.py` là `agents/core/hooks.py`; phần còn lại của hệ thống không cần
biết tên thuộc tính.

Metrics trả lời *có đang hỏng không*, trace trả lời *hỏng ở đâu*. Cần cả hai.

## Thứ tự phụ thuộc

```
core ◄── storage ◄── sources
             ▲   ◄── etl
             │
             └──────► agents ◄── llm
                        ▲  ▲
                 reports┘  └ services ◄── managers ◄── api, scheduler
                                            ▲
                                         queue
```

Mũi tên là "được import bởi". `core` không phụ thuộc gì; `api` và `scheduler` ngồi trên cùng, cả hai đều đi qua `managers`.
`observability` là ngoại lệ có chủ đích: mọi tầng đều import nó.

## Vận hành

`docker compose up` dựng cả app lẫn tầng theo dõi hệ thống:

| Service | Vai trò |
|---|---|
| `api` | Cổng vào — nhận yêu cầu báo cáo, health check |
| `scheduler` | Chạy nền — sync, transform, báo cáo định kỳ |
| `postgres` | Một database, ba schema. Volume tách rời để nâng image không mất dữ liệu |
| `otel-collector` | Điểm gom duy nhất; chia trace về Tempo, metrics về Prometheus |
| `tempo` | Lưu trace — một yêu cầu báo cáo là một trace, từ HTTP tới từng lượt gọi LLM |
| `prometheus` | Lưu metrics — độ trễ sync, số bản ghi mỗi tầng, token đã dùng, tỷ lệ job lỗi |
| `worker` | Rút job ra chạy. `--scale worker=N`, nhưng N vượt số partition thì pod thừa ngồi không |
| `kafka` | Hàng đợi job. KRaft mode, không cần Zookeeper |
| `qdrant` | Vector store — tìm kiếm knowledge base |
| `minio` | Object store, S3 API — file lớn và báo cáo đã render |
| `loki` | Lưu log |
| `promtail` | Gom stdout của container đẩy sang Loki. App không biết Loki tồn tại |
| `vllm` | Model local, tuỳ chọn — bật bằng `--profile local-llm` |
| `grafana` | Dashboard + datasource, provision từ `deploy/grafana/` nên versioned theo code |

App chỉ gửi OTLP tới một địa chỉ (`otel-collector:4317`); đổi backend theo dõi về sau
chỉ cần sửa `deploy/otel/collector.yaml`, không đụng code. Tương tự app chỉ in log ra
stdout — đổi backend log thì sửa `deploy/otel/promtail.yaml`.

## Từ máy dev tới cụm

Toàn bộ hệ chạy **on-premise**, không phụ thuộc dịch vụ cloud nào ngoài lượt gọi LLM cuối.

| | Chạy ở | Dùng khi |
|---|---|---|
| `docker-compose.yml` | máy lập trình viên | code, debug, chạy thử |
| `deploy/helm/` | cụm Kubernetes on-prem | staging, prod |

Hai file khác nhau nhưng **cùng một image** và cùng một bộ biến môi trường. Không có nhánh
`if env == "prod"` nào trong code.

```
git push ──► CI (lint · kiểu · migration · test) ──► build image (tag = SHA)
                  └─ eval chỉ chạy khi đụng prompt/ hoặc llm/     │
                                                                  ▼
                                                      Harbor (registry nội bộ)
                                                                  │
                          CI sửa image.tag trong values ◄─────────┘
                                      │
                          Argo CD thấy git đổi ──► helm upgrade ──► cụm K8s
                                                        ├──► staging (tự sync)
                                                        └──► prod   (người bấm)
```

CI **không** có quyền vào cụm — nó chỉ build image và sửa một dòng trong git. Credential
của cụm nằm ở Argo CD.

### Vì sao cần Kubernetes chứ không phải compose trên host thật

Bốn thứ compose không làm được:

| Cần | K8s làm bằng |
|---|---|
| API scale được | `Deployment.replicas` — nhiều pod sau một Service |
| Pod chết thì tự sống lại | kubelet restart container; Deployment dựng lại pod mất hẳn |
| Traffic tăng thì tự thêm pod | `HorizontalPodAutoscaler` |
| Service gọi nhau | `Service` — một DNS name ổn định, load-balance sẵn |

`docker compose up -d` restart container chết được, nhưng không dời việc sang máy khác khi
**máy** chết, và không tự tăng giảm theo tải.

**Self-healing chỉ hoạt động khi probe đúng.** Pod treo mà vẫn mở cổng thì K8s coi là khoẻ:
không restart, và Service vẫn đẩy request vào. `readinessProbe` quyết định có nhận request,
`livenessProbe` quyết định có restart, `startupProbe` hoãn hai cái kia lúc khởi động — thiếu
cái cuối thì `vllm` bị giết oan vì nạp model mất vài phút.

**HPA: mỗi service một cách đo.** `api` theo CPU. `worker` theo **consumer lag của Kafka**,
vì worker chờ I/O là chính nên CPU thấp trong khi hàng đợi dồn — cần KEDA hoặc
prometheus-adapter. `vllm` **không** autoscale: mỗi pod giữ một GPU, không có GPU rảnh thì
pod mới chỉ Pending.

**Trần cứng của `worker`:** số pod chạy thật = min(replica, số partition). Nên `maxReplicas`
đặt bằng số partition, không đặt cao hơn.

**Stateful chạy dạng `StatefulSet` + PVC**, không phải `Deployment`: Postgres, Kafka, Qdrant,
MinIO cần danh tính ổn định và volume gắn lại đúng pod cũ. On-prem thì phải tự lo lớp
storage (local-path của k3s, hoặc Longhorn nếu muốn volume sang được máy khác) — đây là
phần tốn công nhất khi bỏ cloud. Chi tiết: `deploy/kubernetes/README.md`.

### Helm — deploy tái lập được

Viết tay YAML thì mỗi môi trường một bản sao, sửa một chỗ quên hai chỗ, và không ai trả lời
được "prod đang chạy cấu hình nào". Helm đóng gói thành chart có version: cùng chart +
`values-prod.yaml` luôn ra cùng kết quả.

Hai version đừng nhầm: `version` là của chart (sửa template), `appVersion` là commit SHA của
image (build mới). Rollback chart không tự rollback code.

`scheduler` luôn `replicas: 1` và `strategy: Recreate` — hai scheduler thì mỗi lịch bắn hai
lần, mà `RollingUpdate` dựng pod mới trước khi xoá pod cũ nên có một khoảng hai cái cùng sống.

Migration vẫn chạy trước, khai bằng `pre-upgrade` hook chạy `alembic upgrade head`. Hook fail
thì Helm dừng, pod mới không lên. Secret không nằm trong values — chart chỉ tham chiếu tên
`Secret`. Chi tiết: `deploy/helm/README.md`.

### Argo CD — GitOps

Deploy bằng tay thì không ai trả lời được *prod đang chạy cái gì* và *ai đổi lúc nào*. Argo
lật ngược chiều: git là nguồn sự thật, Argo so cụm với git rồi tự kéo cho khớp.

Hai chỗ cần cẩn thận: `prune` xoá tài nguyên không còn trong git — đặt `false` cho mọi thứ
có state, vì một dòng values sai mà prune mất PVC của Postgres là tai nạn git không cứu
được. Và `selfHeal` ghi đè mọi `kubectl edit` — tiện lúc bình thường, mất đường vá nóng lúc
sự cố. Nên **staging tự sync, prod cần người bấm**. Chi tiết: `deploy/argocd/README.md`.

### Harbor — registry nội bộ

Cụm on-prem thì ảnh cũng phải ở trong nhà: không đụng rate limit Docker Hub, và ảnh chứa
code nội bộ thì không đẩy lên registry công cộng. Ngoài chỗ chứa ảnh, Harbor cho thêm quét
CVE (Trivy), ký ảnh (Cosign), RBAC + audit log, và chính sách dọn tag — mỗi commit một tag,
không dọn thì đĩa đầy trong vài tháng.

Lý do thực dụng nhất là **proxy cache**: mọi image bên thứ ba (postgres, kafka, qdrant,
minio, grafana...) đi qua Harbor, nên cụm dựng lại được kể cả khi mất mạng ra ngoài.

Tag = commit SHA, không bao giờ `latest`: `latest` khiến hai pod cùng manifest chạy hai code
khác nhau, và rollback thì không biết lùi về đâu. Chi tiết: `deploy/registry/README.md`.

Chi tiết biến môi trường và secret: `deploy/envs/README.md`.

## Mở rộng sau này

Khi một module phình to thì tách thành thư mục, giữ nguyên tên:
`sources/slack.py` → `sources/slack/{client.py,parser.py}`. Không cần dựng sẵn tầng
`domain/application/infrastructure` khi chưa có gì để bỏ vào.

## Chất lượng báo cáo

Test bắt lỗi code. Báo cáo kém đi không làm test đỏ — output vẫn đúng format, chỉ là tệ
hơn. Đó là việc của `evals/`: golden set các cặp *dữ liệu gold → báo cáo con người chấp
nhận được*. Đổi prompt, đổi model, nâng version agent đều phải chạy lại và so điểm với
lần trước. Điểm tụt là chặn merge.
