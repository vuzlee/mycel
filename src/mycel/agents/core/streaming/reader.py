"""Đọc sự kiện thô từ model và đẩy qua mapper.

Giữ nguyên thứ tự và không nuốt lỗi: model đứt giữa chừng phải thành một sự kiện lỗi
trong luồng, không phải một luồng im lặng rồi kết thúc — client không phân biệt được
"xong" với "chết".
"""
