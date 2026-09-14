"""Nơi ráp toàn bộ tầng HTTP lại.

Đây là thứ `uvicorn mycel.api.app:app` trỏ tới, và là file duy nhất biết có
những nhóm route nào. Thêm một nhóm endpoint mới = thêm một file trong
routes/ và một dòng include_router ở đây.

File này chỉ lắp ráp: tạo app, gắn router, bật middleware, nối observability.
Không chứa endpoint, không chứa nghiệp vụ.
"""
