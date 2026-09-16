"""Tìm kiếm knowledge base bằng embedding. Backend: Qdrant.

  client.py      kết nối Qdrant, một client dùng chung
  collections.py khai báo collection: tên, số chiều, metric, cấu hình index
  indexer.py     từ gold sinh embedding rồi upsert vào collection
  search.py      truy vấn: k-NN + lọc theo metadata

Vì sao không phải `pgvector`: xem `storage/__init__.py`.

Nguồn của embedding là **gold**, không phải raw — cùng một hợp đồng mà agent đọc.
Nhờ vậy kết quả tìm kiếm và kết quả truy vấn bảng không bao giờ mâu thuẫn nhau.
"""
