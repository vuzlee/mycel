"""Đọc raw, ghi silver: đã chuẩn hoá schema, khử trùng lặp, ép kiểu.

Khử trùng lặp dựa trên khoá tự nhiên của nguồn (message id, thread id), không
dựa trên hash cả bản ghi — provider sửa một trường là hash đổi, thành bản ghi mới.
"""
