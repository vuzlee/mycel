"""Connector tới từng provider: Slack, Gmail, Confluence...

Mỗi provider một module, cùng một interface: nhận khoảng thời gian cần sync, trả bản ghi
thô, ghi xuống `raw`. Không làm sạch, không chuẩn hoá — việc đó của `etl/`.

Thêm nguồn mới = thêm một file ở đây, không sửa code cũ. Cấu hình riêng của từng nguồn
(endpoint, scope, rate limit) nằm ở `config/sources/`.
"""
