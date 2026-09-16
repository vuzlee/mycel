"""Vỏ HTTP — mỏng nhất có thể.

  app.py           tạo app, gắn router, bật middleware, nối observability
  middleware.py    chỉ `request_id` — phần còn lại dùng đồ có sẵn, xem docstring trong đó
  dependencies.py  thứ controller khai qua Depends(): xác thực, session DB, phân trang
  health.py        /health/live và /health/ready — không thuộc miền nghiệp vụ nào

Endpoint nghiệp vụ không nằm ở đây. Chúng nằm trong managers/<miền>/controller.py,
app.py chỉ gom lại.
"""
