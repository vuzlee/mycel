"""Mỗi tầng dữ liệu một repository: `raw.py`, `silver.py`, `gold.py`.

Chia theo tầng chứ không theo bảng, vì quy tắc truy cập gắn với tầng: `sources/`
chỉ được ghi raw, `etl/` đọc dưới ghi trên, agent chỉ đọc gold. Tách file như vậy
thì vi phạm nguyên tắc nhìn thấy ngay ở dòng import.
"""
