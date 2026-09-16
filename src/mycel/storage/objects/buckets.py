"""Khai báo bucket và vòng đời lưu trữ.

  mycel-raw        file nguyên bản tải từ provider
  mycel-reports    báo cáo đã render (PDF, HTML)

Đặt lifecycle rule ngay từ đầu: không có nó thì bucket chỉ lớn lên, và chi phí là
thứ không ai nhìn cho tới lúc hoá đơn về.
"""
