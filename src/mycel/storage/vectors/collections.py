"""Khai báo collection: tên, số chiều, metric khoảng cách, cấu hình index.

Số chiều gắn chặt với model embedding. Đổi model là phải tạo collection mới rồi
index lại toàn bộ — không có cách nào trộn hai không gian vector khác nhau trong
cùng một collection. Nên tên collection phải mang version của model.
"""
