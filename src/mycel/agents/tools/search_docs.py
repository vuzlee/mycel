"""Tìm knowledge base bằng ngữ nghĩa. Gọi `storage/vectors/search.py`.

Trả về đoạn văn bản kèm **nguồn** (bản ghi gold nào, link gốc) — không trả mỗi
nội dung. Thiếu nguồn thì `reviewer.py` không có cách nào kiểm chứng, và báo cáo
thành lời khẳng định không trích dẫn được.

Quyền xem truyền xuống thành filter của Qdrant, không lọc sau khi có kết quả.
"""
