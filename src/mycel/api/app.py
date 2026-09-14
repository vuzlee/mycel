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
"""
