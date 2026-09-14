"""Vỏ HTTP. Chỉ nhận request, gọi services, trả response. Không chứa nghiệp vụ.

  app.py     ráp app: tạo FastAPI, gắn router, middleware, observability
  routes/    endpoint theo nhóm tài nguyên — mỗi file một router
  schemas/   hình dạng dữ liệu vào/ra qua HTTP
"""
