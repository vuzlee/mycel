"""Thứ một lượt chạy agent mang theo suốt vòng đời: job_id, budget, session DB, trace context.

Truyền qua tham số thay vì biến toàn cục, nên chạy nhiều agent song song không giẫm lên
nhau. `hooks.py` đọc `budget` và `job_id` từ đây — agent con nhận cùng một object với
agent cha nên token của nó cũng được cộng vào đúng trần.
"""
