"""Trả lời *khi nào chạy*.

Sync nguồn theo giờ, transform sau khi sync xong, báo cáo hàng ngày/tuần.

Gọi thẳng pipeline trong managers/ — đúng chỗ controller gọi, chỉ bỏ qua mắt
xích HTTP. Không tự gọi HTTP vào chính mình.
"""
