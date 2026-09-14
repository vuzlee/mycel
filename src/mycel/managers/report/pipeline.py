"""Chuỗi nghiệp vụ của miền báo cáo.

Pipeline định nghĩa *thứ tự* các bước; mỗi bước là một service làm một việc:

  request_report()
    1. permission_service    người này được xem nguồn này không
    2. queue_service         đẩy job, trả job_id
                             --- worker nhận job, chạy tiếp ---
    3. gather_service        truy vấn gold lấy dữ liệu cần
    4. analyze_service       giao cho agents/ phân tích
    5. render_service        dựng artifact qua reports/

Pipeline không tự làm việc gì, chỉ ghép service lại. Service dùng lại được ở
pipeline khác — gather_service cũng phục vụ miền sync.
"""
