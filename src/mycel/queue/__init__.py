"""Tầng job chạy nền trên Kafka: định nghĩa job, retry, dead-letter, idempotency key.

**Không phải broker.** Kafka chạy ngoài, khai trong `docker-compose`. Thư mục này là tầng
nằm *trên* Kafka — đổi broker thì sửa ở đây, phần còn lại của hệ thống không biết.

Trả lời *chạy cái gì, lỗi thì sao*; `scheduler/` trả lời *khi nào chạy*.

  job.py       hình dạng một job: payload, idempotency key, số lần đã retry, trace context
  producer.py  đẩy job lên topic — cửa vào là `services/enqueue.py`
  consumer.py  vòng lặp poll/commit của worker
  retry.py     topic retry theo tầng + dead-letter
  context.py   mang trace context qua ranh giới process

**Kafka là log có thứ tự, không phải hàng đợi việc**, nên bốn thứ dưới đây phải tự dựng —
không có cái nào là mặc định, và cả bốn đều hỏng lặng lẽ nếu làm sai:

1. **Retry không lẻ được.** Consumer commit theo offset, nên job lỗi mà `seek` lại thì
   chặn cả partition. Cách làm: đẩy sang topic retry rồi commit tiếp — xem `retry.py`.
2. **Số partition chặn song song, không phải số worker.** 3 partition thì worker thứ 4
   ngồi không. Đặt partition theo mức scale tối đa *dự kiến* ngay từ đầu: tăng được nhưng
   không giảm, và tăng thì phá thứ tự theo key.
3. **Job chạy lâu bị coi là chết.** `max.poll.interval.ms` mặc định 5 phút; sinh báo cáo
   mất "vài phút" nên nằm đúng vùng nguy hiểm — quá hạn là rebalance và job chạy lại từ
   đầu. Phải nâng hẳn giá trị này, hoặc tách việc ra khỏi vòng poll.
4. **Commit sau khi xong, không phải sau khi nhận.** Commit sớm thì worker chết giữa
   đường là mất job. Commit muộn thì job có thể chạy hai lần — nên idempotency key trong
   `job.py` là bắt buộc, không phải tuỳ chọn.

Đổi lại, Kafka cho thứ hàng đợi thường không có: giữ lại log nên replay được, và thêm
consumer group khác đọc cùng luồng mà không ảnh hưởng worker hiện tại.
"""
