"""Chặn agent tự đốt tiền.

  runaway      quá số vòng lặp hoặc quá số tool call cho một lượt thì dừng
  degenerate   model lặp lại chính nó (cùng tool, cùng tham số) thì dừng
  retry_prompt Output sai schema thì nhắc lại kèm lỗi cụ thể, không retry mù

Khác `llm/budget.py`: budget đếm tiền của cả job, guard đếm hành vi của một lượt chạy.
Một vòng lặp hỏng chạm guard trong vài giây, chạm budget thì đã tốn tiền rồi.
"""
