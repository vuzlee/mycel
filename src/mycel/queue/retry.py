"""Retry theo tầng và dead-letter — trên Kafka phải tự dựng, không có sẵn.

Không seek lại offset cũ: một job hỏng sẽ chặn mọi job sau nó trong cùng partition. Thay
vào đó chuyển job sang topic khác rồi commit tiếp, partition chảy tiếp bình thường:

    jobs            lần đầu
    jobs.retry.1m   chờ ~1 phút rồi thử lại
    jobs.retry.10m  lâu hơn
    jobs.dlq        hết lượt — giữ lại để xem, không mất âm thầm

Số lần đã retry đếm trong header của message, vì bản thân Kafka không đếm hộ.

Chờ thực hiện bằng cách consumer của topic retry ngủ tới khi message đủ tuổi rồi mới xử
lý — Kafka không có delayed message như RabbitMQ.

Trace context đi theo header qua cả bốn topic, nên một job vào được `jobs.dlq` vẫn mở lại
được trace từ lúc người dùng bấm nút.
"""
