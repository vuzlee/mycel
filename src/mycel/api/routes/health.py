"""Health check.

  /health/live   — process còn sống không. Dùng cho restart policy.
  /health/ready  — có sẵn sàng nhận request không (DB kết nối được, migration đã chạy).
                   Dùng cho load balancer, tránh đẩy traffic vào instance chưa sẵn sàng.
"""
