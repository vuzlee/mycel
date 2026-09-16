"""Engine, session, repository cho ba tầng raw/silver/gold.

  engine.py       tạo engine + connection pool, đọc DSN từ config
  session.py      scope của một session, commit/rollback
  repositories/   mỗi tầng một repository: raw, silver, gold

Giữ nguyên tắc: mọi câu SQL nằm trong repository. Pipeline và agent gọi hàm có
tên nghiệp vụ, không tự ghép SQL.
"""
