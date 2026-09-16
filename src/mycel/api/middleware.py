"""Middleware tự viết — chỉ có một: gắn `request_id` cho mỗi request.

Những thứ còn lại **không tự viết**, vì đã có sẵn và tự viết là bảo trì lại thứ đã chuẩn hoá:

  tracing      `FastAPIInstrumentor.instrument_app(app)` — theo đúng semantic convention
               của OTel (`http.route`, `http.status_code`), tự viết sẽ lệch
  CORS         `CORSMiddleware` của Starlette
  lỗi          `@app.exception_handler(...)` — cơ chế riêng của FastAPI, không phải middleware
  rate limit   Nginx/ingress chặn trước khi chạm app; cần theo user thì dùng `slowapi`
  xác thực     `Depends()` — xem `dependencies.py`, ở đó nói vì sao không để ở đây

Vì sao `request_id` vẫn phải tự viết: phần giá trị là đặt id vào `contextvars` để
`observability/logging.py` tự đọc, nhờ vậy controller không phải viết
`log.info(..., request_id=rid)` ở từng dòng. Logger là của mình nên đoạn nối đó không
thư viện nào làm hộ; đã vậy thì viết luôn, khỏi thêm dependency.

Có sẵn trong header thì dùng lại id đó (giữ được chuỗi khi đi qua nhiều service), không
thì sinh mới. Trả về trong response header để người báo lỗi đưa đúng id cần tra.

**Viết dạng pure ASGI, đừng dùng `BaseHTTPMiddleware`.** Cái đó buffer response nên làm
nghẽn SSE — mà `agents/core/streaming/` sinh ra chính là để stream. Lỗi này không báo gì,
chỉ là token về thành một cục ở cuối.

**`contextvars` (built-in của Python, không phải của FastAPI) chỉ đi theo async task.**
Ranh giới nó không vượt qua:

    await                   giữ nguyên — cùng task
    create_task()           task con copy context lúc tạo; con set lại thì cha không thấy
    run_in_executor/thread  KHÔNG tự mang theo, phải truyền tay
    process khác            mất hẳn — xem `queue/__init__.py`

Dòng cuối là chỗ gặp thật: job chạy ở worker process khác, nên id không tự đi theo.
"""
