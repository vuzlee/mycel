"""Endpoint HTTP của miền đồng bộ.

  POST /sync/{source}   kéo một nguồn ngay, không đợi lịch
  GET  /sync/status     lần sync gần nhất của từng nguồn

Chủ yếu dùng khi debug hoặc khi cần dữ liệu mới gấp. Đường chính là
scheduler/ tự gọi pipeline theo giờ, không qua HTTP.
"""
