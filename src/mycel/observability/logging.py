"""Log có cấu trúc, mỗi dòng một JSON, luôn kèm `trace_id` · `request_id` · `job_id`.

Ba id, ba nguồn khác nhau — chỗ này hay nhầm:

    trace_id    OTel tự sinh sau khi instrument. Đọc từ span hiện tại, không phải truyền tay
    request_id  mình sinh ở `api/middleware.py`, đặt vào contextvars. Trả về cho client —
                người báo lỗi đưa đúng id này
    job_id      sinh khi đẩy vào `queue/`. Nối request với việc chạy nền sau đó

Logger không tự biết `trace_id`: mỗi lần log phải đọc span hiện tại rồi gắn vào. Đó là
đoạn nối duy nhất phải viết tay, và cũng là thứ khiến từ một dòng log nhảy thẳng sang
trace tương ứng được, không phải dò theo giờ.

Không có id nào thì vẫn log, không raise — log mà làm chết request là đổi một lỗi nhỏ
thành một lỗi to.

**In ra stdout, không gửi đi đâu cả.** Promtail gom stdout của container rồi đẩy sang
Loki; trong K8s cũng đúng cơ chế đó. Nhờ vậy module này không biết Loki tồn tại, và đổi
backend log về sau chỉ sửa `deploy/otel/promtail.yaml`.

`trace_id` nằm trong **nội dung** dòng JSON, không phải label của Loki: label có bao
nhiêu giá trị khác nhau thì Loki tạo bấy nhiêu stream, mà trace_id thì gần như không
lặp lại. Grafana vẫn bắt được bằng derived field — xem `deploy/grafana/datasources/`.
"""
