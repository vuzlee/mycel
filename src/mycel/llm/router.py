"""Chọn backend cho mỗi lượt gọi LLM.

Ranh giới:
  local  — việc khối lượng lớn, đầu ra ngắn, hoặc dữ liệu nhạy cảm không muốn rời máy.
           Phân loại, trích entity, chấm điểm liên quan, tóm tắt từng bản ghi.
  cloud  — suy luận cuối: tổng hợp nhiều nguồn, viết báo cáo, quyết định cần ngữ cảnh dài.

Gọi LLM ở nơi khác đều phải đi qua đây, không import thẳng SDK provider.
"""

from enum import Enum


class Tier(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"
