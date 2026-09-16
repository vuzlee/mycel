"""Vòng chạy của một agent: prompt vào, tool được gọi, output có cấu trúc đi ra.

Một `run()` gồm: dựng message từ prompt + ngữ cảnh, gọi model qua `llm/`, nếu model đòi
tool thì gọi tool rồi đưa kết quả về, lặp tới khi có câu trả lời cuối. Output được
validate theo schema; sai format thì retry chứ không để dữ liệu hỏng đi tiếp.

Có hai cửa vào: `run()` trả kết quả một lần, `run_stream()` trả dần qua `core/streaming/`.
Cả hai đi qua cùng một vòng lặp — khác nhau chỉ ở chỗ nhận sự kiện.
"""
