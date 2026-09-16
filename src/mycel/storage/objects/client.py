"""Client S3 dùng chung, và ký presigned URL.

Presigned URL là lý do chính để tách object store: API trả cho client một URL có
hạn thay vì tự đọc file rồi stream lại. File 200MB không đi qua process API.
"""
