"""Vòng đời một session: mở, commit khi xong, rollback khi lỗi, luôn đóng.

Một request = một session. Đừng chia sẻ session giữa các task chạy song song —
session của SQLAlchemy không an toàn với concurrency.
"""
