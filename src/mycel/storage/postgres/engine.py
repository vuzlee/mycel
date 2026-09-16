"""Tạo engine và connection pool, một lần lúc khởi động.

Pool size phải tính theo tổng số process, không theo từng process: `api` chạy
N worker uvicorn, `worker` scale theo partition Kafka — mỗi cái giữ pool riêng.
Cộng lại vượt `max_connections` của Postgres thì lỗi chỉ hiện lúc tải cao.
"""
