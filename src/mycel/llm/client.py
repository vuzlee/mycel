"""Cổng gọi model thật — file duy nhất trong Mycel được import SDK provider.

Nhận một spec đã phân giải từ `router.py` và một danh sách message, trả về kết quả hoặc
một luồng delta. Nuốt hết khác biệt giữa provider: tên tham số, hình dạng tool call,
cách báo lỗi rate limit.

Mọi lượt gọi đi qua đây đều được `usage.py` đếm và `cache.py` hỏi trước.
"""
