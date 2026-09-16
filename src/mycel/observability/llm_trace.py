"""Gắn thuộc tính riêng của LLM lên span, theo quy ước Langfuse đọc được.

Một lượt gọi model là một span con; input, output, model, token, chi phí nằm trên đó.
Một yêu cầu báo cáo vì vậy là một cây: HTTP -> pipeline -> queue -> worker ->
orchestrator -> từng agent -> từng lượt gọi model. Báo cáo sai số thì lần ngược được về
đúng lượt gọi đã sinh ra nó.

Cây đó chỉ liền khi hai chỗ làm đúng: `queue/context.py` nối qua ranh giới process, và
`agents/core/hooks.py` gọi vào đây cho mọi run kể cả agent con. Thiếu một chỗ là trace
gãy làm đôi mà không báo lỗi.

Chỗ gọi vào là `agents/core/hooks.py`; phần còn lại của hệ thống không cần biết tên
thuộc tính.
"""
