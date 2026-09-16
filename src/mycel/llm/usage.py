"""Đếm một lượt gọi model tốn gì: token vào/ra, cache hit, thời gian, số lần gọi.

Một chỗ đếm duy nhất, ba nơi dùng: `budget.py` cộng dồn theo job, `observability/` gắn
lên span, log ghi ra để xem lại. Đếm rải rác ở nhiều nơi thì ba con số sẽ lệch nhau.
"""
