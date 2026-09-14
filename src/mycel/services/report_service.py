"""Nghiệp vụ: yêu cầu và lấy báo cáo.

Cùng một hàm phục vụ hai nơi gọi:
  - api/routes/reports.py  — người bấm nút
  - scheduler/             — tới giờ chạy định kỳ

Việc ở đây là điều phối: kiểm tra quyền, đẩy job vào hàng đợi, trả job_id.
Không tự chạy agent - việc đó mất vài phút, phải qua jobs/.
"""
