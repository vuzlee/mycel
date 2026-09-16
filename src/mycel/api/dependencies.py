"""Thứ controller khai qua `Depends()`: xác thực, session DB, phân trang.

**Xác thực để ở đây chứ không phải middleware**, vì `Depends()` hơn ở ba điểm:

  - Middleware chạy cho *mọi* route, nên phải tự duy trì danh sách loại trừ `/health`,
    `/docs`, `/openapi.json`. Dependency thì route nào khai mới có.
  - Dependency vào được OpenAPI schema — `/docs` hiện ổ khoá, client sinh code biết cần token.
  - Controller nhận thẳng `user: User = Depends(current_user)`, có kiểu, mypy strict kiểm
    được. Middleware chỉ nhét vào `request.state` — mypy không thấy gì.

Dependency chỉ trả lời *anh là ai*; còn *anh được xem báo cáo nào* là việc của
`services/permission.py`, vì nó cần ngữ cảnh nghiệp vụ mà tầng HTTP không có.
"""
