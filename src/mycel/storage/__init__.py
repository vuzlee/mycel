"""Ba kho lưu trữ, ba loại dữ liệu khác nhau. Mọi truy cập đi qua đây.

  postgres/    state giao dịch: ba tầng raw/silver/gold, job, quyền
  vectors/     embedding cho tìm kiếm knowledge base (Qdrant)
  objects/     file lớn: PDF nguồn, báo cáo đã render (MinIO, S3 API)

Vì sao tách ba chỗ mà không nhét hết vào Postgres:

- **Vector.** `pgvector` chạy được nhưng tới vài triệu vector thì index HNSW ăn
  RAM tranh với chính workload giao dịch trên cùng instance. Tách ra thì scale
  hai bên độc lập.
- **File.** Blob trong Postgres làm database phình, backup chậm, và mỗi lần đọc
  phải kéo cả file qua connection của pool. Object store sinh ra để làm việc đó.

Mọi câu SQL, mọi truy vấn vector, mọi thao tác file nằm ở đây — không rải rác
trong pipeline hay agent. Đổi schema hay đổi kho thì sửa một chỗ.
"""
