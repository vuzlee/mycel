"""Trả lời *khi nào chạy*: sync nguồn theo giờ, transform sau khi sync xong, báo cáo định kỳ.

Gọi thẳng pipeline trong `managers/` — đúng chỗ controller gọi, chỉ bỏ qua mắt xích HTTP.
Không tự gọi HTTP vào chính mình.

Khác `queue/`: ở đây là lịch, bên kia là job và cách xử lý khi job fail.
"""
