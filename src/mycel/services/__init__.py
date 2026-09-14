"""Một file = một việc đơn lẻ, làm xong một chuyện.

Service là mắt xích; pipeline trong managers/ là chuỗi ghép các mắt xích lại.
Vì vậy service phải dùng lại được: gather_service phục vụ cả miền báo cáo lẫn
miền đồng bộ.

Service không biết mình đang nằm trong chuỗi nào, cũng không biết ai gọi nó —
HTTP hay scheduler đều như nhau. Luật nghiệp vụ phức tạp (transform, suy luận,
dựng artifact) nằm ở etl/, agents/, reports/; service chỉ gọi tới.
"""
