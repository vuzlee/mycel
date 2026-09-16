"""Cấu hình khung agent: chọn model, tham số sinh, giới hạn vòng lặp.

Chỉ chứa knob mà *mọi* agent đều cần. Knob riêng của một agent nằm ở chính agent đó.

Model khai báo dạng `'<tier>:<model_name>'` (`local:qwen3-4b`, `cloud:claude-sonnet-5`);
tier được `llm/router.py` dịch sang backend thật. Nhờ vậy đổi model là đổi biến môi
trường, không sửa code.
"""
