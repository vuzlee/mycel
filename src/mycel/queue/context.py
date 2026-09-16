"""Mang trace context và request_id qua ranh giới process, để trace không đứt ở hàng đợi.

`contextvars` chỉ sống trong một process. Job đi qua Kafka sang worker là mất hết, nên
phải đóng gói thủ công ở hai đầu:

    producer  inject()  — ghi trace context vào header của message
    consumer  extract() — khôi phục trước khi chạy, span của job thành con của span request

Đặt ở **header**, không phải payload: header đi theo message qua cả topic retry và
dead-letter mà không phải chạm vào nội dung job.

Dùng `TraceContextTextMapPropagator` của OTel (chuẩn W3C traceparent), không tự bịa
format — cùng chuẩn với header HTTP nên sau này thêm service khác vẫn nối được.

Quên một đầu thì không có lỗi nào báo: trace vẫn ghi, chỉ là thành hai cây rời nhau.
"""
