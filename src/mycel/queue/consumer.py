"""Vòng lặp poll của worker: nhận job, chạy, commit.

Ba ràng buộc của Kafka phải tôn trọng ở đây, cả ba đều hỏng lặng lẽ:

  enable_auto_commit=False   tự commit là commit trước khi job xong -> chết giữa đường
                             là mất job
  commit sau khi xong        thứ tự đúng: chạy -> commit. Không phải ngược lại
  max_poll_interval_ms       nâng hẳn lên (mặc định 5 phút) vì sinh báo cáo mất vài phút.
                             Quá hạn là Kafka coi worker này chết, rebalance, job chạy lại

Job lỗi thì **không** seek lại — làm vậy chặn cả partition. Đẩy sang topic retry rồi
commit tiếp, xem `retry.py`.

Gọi `context.extract()` ngay khi nhận, trước khi chạy, để span của job nối vào span của
request đã tạo ra nó.
"""
