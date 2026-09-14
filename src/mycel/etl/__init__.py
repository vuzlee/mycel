"""Các bước biến đổi dữ liệu: raw -> silver -> gold.

Đây là ETL chạy nền theo lịch, không phải chuỗi xử lý request. Chuỗi nghiệp vụ
của một request nằm ở managers/<miền>/pipeline.py.

Mỗi bước là một hàm thuần: đọc tầng dưới, ghi tầng trên, idempotent — chạy lại
hai lần cho cùng kết quả. checks/ kiểm tra sau mỗi bước.
"""
