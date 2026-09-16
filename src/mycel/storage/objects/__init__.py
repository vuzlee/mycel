"""File lớn: PDF nguồn, ảnh đính kèm, báo cáo đã render. Backend: MinIO (S3 API).

  client.py    kết nối, ký URL
  buckets.py   khai báo bucket và vòng đời lưu trữ
  files.py     put/get/xoá, đọc ghi theo luồng

Dùng S3 API nên chuyển sang S3 thật (hoặc R2, GCS-compat) chỉ là đổi endpoint và
credential — không sửa code.

Postgres giữ **metadata** của file (ai sở hữu, thuộc báo cáo nào, key trong bucket);
bucket giữ **nội dung**. Không bao giờ ngược lại.
"""
