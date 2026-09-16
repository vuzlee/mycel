"""Hình dạng một job: loại việc, payload, idempotency key, số lần đã retry, trace context.

**Idempotency key là bắt buộc trên Kafka**, không phải tuỳ chọn. Kafka cho đảm bảo
at-least-once: commit sau khi xong nghĩa là worker chết giữa đường thì job chạy lại, và
nó *đã* làm xong một phần. Không có key thì một báo cáo sinh ra hai lần.

Key nên suy ra từ nội dung việc (miền + khoảng thời gian + tham số), không phải UUID sinh
mới mỗi lần — UUID thì hai lần gọi là hai key khác nhau, đúng cái đang muốn tránh.

Kafka message key thì dùng cho việc khác: nó quyết định partition, tức là quyết định thứ
tự. Cùng một nguồn dữ liệu nên vào cùng partition để hai job sync không chạy chồng nhau.

Trace context nằm trong header của message (xem `context.py`), không nằm trong payload:
header đi theo message qua cả topic retry và dead-letter, nên job hỏng vẫn mở lại được
trace để xem vì sao.
"""
