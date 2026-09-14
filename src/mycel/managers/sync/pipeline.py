"""Chuỗi nghiệp vụ của miền đồng bộ.

  sync_source(name, khoảng_thời_gian)
    1. fetch_service      gọi sources/, ghi payload nguyên bản xuống raw
    2. transform_service  chạy etl/ raw -> silver -> gold
    3. check_service      chạy etl/checks/; fail thì dừng, không ghi lên tầng trên

Mỗi bước idempotent — chạy lại cùng khoảng thời gian cho cùng kết quả.
"""
