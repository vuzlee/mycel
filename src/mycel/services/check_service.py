"""Chạy etl/checks/ sau mỗi bước transform.

Thiếu cột, null bất thường, số đếm lệch quá ngưỡng thì raise — pipeline dừng,
không ghi lên tầng trên. Provider đổi schema mà không báo là chuyện thường;
không check thì gold hỏng lặng lẽ và agent tự tin báo cáo số sai.
"""
