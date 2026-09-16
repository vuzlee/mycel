"""put/get/xoá, đọc ghi theo luồng.

Luôn stream, không `read()` cả file vào RAM: một PDF 200MB nhân với vài job chạy
song song là đủ giết worker bằng OOM — mà Kafka sẽ coi đó là worker chết rồi chạy
lại chính job đó, lặp vô hạn.
"""
