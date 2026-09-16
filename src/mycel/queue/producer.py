"""Đẩy job lên topic. Cửa vào từ nghiệp vụ là `services/enqueue.py`.

Chọn partition bằng message key (thường là tên nguồn hoặc id miền), để job cùng một đối
tượng giữ được thứ tự và không chạy chồng nhau.

`acks=all` chứ không phải mặc định: mất một job báo cáo thì người dùng chờ mãi không thấy
gì, đắt hơn nhiều so với chậm thêm vài chục ms lúc gửi.

Gọi `context.inject()` trước khi gửi, nếu không trace đứt ngay tại đây.
"""
