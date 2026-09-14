"""Trần chi phí theo từng job.

Đếm token trước khi gửi, cộng dồn theo job_id, vượt trần thì raise thay vì gọi tiếp —
một agent lặp vô hạn không được phép đốt hết budget tháng.
"""
