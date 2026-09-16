"""Nơi luồng sự kiện chảy tới: SSE cho trình duyệt, WebSocket, file để xem lại, hoặc bỏ đi.

Agent không biết mình đang stream đi đâu — chỉ ghi vào sink. Nhờ vậy test chạy được với
sink ghi vào list trong bộ nhớ, không cần dựng HTTP.
"""
