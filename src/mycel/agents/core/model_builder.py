"""Từ spec `'<tier>:<model_name>'` dựng ra client model đã sẵn sàng gọi.

Parse spec, hỏi `llm/router.py` xem tier nào, lấy credential tương ứng, trả về client đã
gắn timeout và số lần retry. Đây là chỗ duy nhất biết provider nào cần tham số gì —
`agent.py` chỉ nhận về một thứ gọi được.
"""
