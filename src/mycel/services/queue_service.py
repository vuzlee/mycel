"""Đẩy một việc vào hàng đợi và trả job_id.

Gói jobs/ lại thành một lời gọi: pipeline không cần biết hàng đợi chạy bằng gì.
Mỗi job có idempotency key nên gọi hai lần không sinh hai báo cáo trùng.
"""
