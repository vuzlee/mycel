"""Tool: năng lực agent gọi được.

  query_gold.py     truy vấn tầng gold qua storage/postgres/
  search_docs.py    tìm knowledge base qua storage/vectors/
  chart.py          dựng spec biểu đồ
  compute.py        phần trăm, tăng trưởng, thống kê cơ bản

Hai cách tra cứu, hai loại câu hỏi: `query_gold` trả lời câu có số liệu chính xác
("doanh thu quý 3"), `search_docs` trả lời câu mơ hồ ("ai đã bàn về vụ này").
Nhầm chỗ thì agent đi tìm số bằng tìm kiếm ngữ nghĩa và bịa ra con số gần đúng.
"""
