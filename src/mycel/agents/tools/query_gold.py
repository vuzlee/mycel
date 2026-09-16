"""Tool truy vấn tầng gold.

Đi qua `storage/` chứ không tự viết SQL, và chỉ đọc gold — agent không chạm raw/silver.
Có trần số dòng trả về: một câu quét cả bảng sẽ làm tràn context và tốn tiền vô ích.
"""
