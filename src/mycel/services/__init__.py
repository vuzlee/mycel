"""Một file = một nghiệp vụ đầu-cuối.

Tầng này tồn tại vì mỗi nghiệp vụ có ít nhất hai nơi gọi: api (người bấm) và
scheduler (tới giờ). Không có nó thì logic bị chép đôi.

Services điều phối; luật nghiệp vụ thật nằm ở pipeline/, agents/, reports/.
"""
