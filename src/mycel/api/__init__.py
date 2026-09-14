"""Vỏ HTTP — mỏng nhất có thể.

  app.py     tạo app, gắn controller của từng manager, middleware, observability
  health.py  /health/live và /health/ready — không thuộc miền nghiệp vụ nào

Endpoint nghiệp vụ không nằm ở đây. Chúng nằm trong managers/<miền>/controller.py,
app.py chỉ gom lại.
"""
