"""Truy vấn: k-NN kèm lọc theo metadata (nguồn, khoảng thời gian, quyền xem).

Lọc phải làm **trong** Qdrant chứ không lọc sau khi lấy top-k: lấy 10 kết quả rồi
mới bỏ những cái không được phép xem thì có khi còn 2. Quyền là filter, không phải
bước hậu xử lý.

Agent gọi qua tool `agents/tools/`, không import thẳng module này.
"""
