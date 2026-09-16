"""Agent điều phối: nhận yêu cầu báo cáo, chia thành task, giao agent chuyên môn, ghép kết quả.

Không tự phân tích số liệu hay viết chữ — nó quyết định *cần những gì* rồi giao việc.
Task độc lập thì chạy song song; task nào fail thì báo cáo vẫn ra được, phần thiếu được
ghi rõ thay vì bịa.

Tên không phải "manager" để khỏi lẫn với `managers/` — cái kia là điểm vào HTTP theo miền.
"""
