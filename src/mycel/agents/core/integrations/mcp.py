"""Client MCP: gắn tool từ server ngoài vào agent mà không phải viết wrapper.

Kết nối server đã khai trong config, đọc danh sách tool, dựng thành tool agent gọi
được. Tool MCP đi qua đúng đường như tool nội bộ — cùng chỗ log, cùng chỗ tính trace,
cùng guard đếm số lần gọi.

Tool ngoài là mã người khác viết: cần timeout, cần giới hạn kích thước kết quả trả về.
"""
