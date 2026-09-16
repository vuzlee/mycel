"""Nơi ráp toàn bộ tầng HTTP lại.

`uvicorn mycel.api.app:app` trỏ vào đây. Đây là file duy nhất biết hệ thống có
những miền nào:

    include_router(managers.report.controller.router)
    include_router(managers.sync.controller.router)
    include_router(health.router)

Thêm một miền = thêm một thư mục trong managers/ và một dòng ở đây. Không đụng
miền đang có.

File này chỉ lắp ráp: tạo app, gắn router, bật middleware, nối observability.
Không chứa endpoint, không chứa nghiệp vụ.

Phần lắp ráp, gần như toàn là gọi thư viện có sẵn:

    observability.tracing.setup()          dựng OTel một lần, TRƯỚC mọi thứ khác
    FastAPIInstrumentor.instrument_app()   span gốc cho mỗi request
    add_middleware(RequestIdMiddleware)    cái duy nhất tự viết
    add_middleware(CORSMiddleware)         origin đọc từ config theo môi trường
    add_exception_handler(...)             một hình dạng lỗi duy nhất, kèm request_id,
                                           không rò traceback ra ngoài

`tracing.setup()` phải chạy trước khi instrument, nếu không span rơi vào provider rỗng —
không lỗi, chỉ là trace trống.

Thứ tự gắn có ý nghĩa: `request_id` phải ngoài cùng, để span và mọi dòng log sinh ra sau
đó đều có id mà gắn vào. Starlette chạy middleware theo thứ tự **ngược** với lúc
`add_middleware` — cái thêm sau nằm ngoài, nên `request_id` thêm *sau* các middleware khác.

Xác thực không nằm ở đây: nó là `Depends()`, xem `dependencies.py`.
"""
