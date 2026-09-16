"""Trả kết quả dần thay vì đợi agent chạy xong.

Một báo cáo mất vài chục giây; im lặng suốt thời gian đó là trải nghiệm tệ và cũng khó
debug. Tầng này biến sự kiện thô từ model (delta token, tool bắt đầu/kết thúc) thành
một luồng sự kiện có tên, ổn định, để client hiển thị và để log đọc lại được.

  reader.py    đọc sự kiện thô từ model
  mapper.py    dịch sự kiện thô sang sự kiện miền
  envelope.py  hình dạng một sự kiện trên đường dây
  sink.py      nơi sự kiện chảy tới: SSE, WebSocket, file, bỏ đi
  output/      gom delta lại thành output hoàn chỉnh theo từng dạng
"""
