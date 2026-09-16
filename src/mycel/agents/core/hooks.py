"""Móc vào trước/sau mỗi lượt chạy agent: gắn trace, log usage, cộng budget.

Đây là **chỗ duy nhất nhìn thấy mọi run**, kể cả sub-agent do worker gọi — usage của
sub-agent không tự cộng lên agent cha, nên cộng budget phải làm ở đây chứ không ở chỗ
gọi model, nếu không worker sẽ lọt sổ.

  before_run   mở span, gắn tên trace · job_id · input
  after_run    ghi output vào trace, log token/thời gian, gọi budget.record(usage)
"""
