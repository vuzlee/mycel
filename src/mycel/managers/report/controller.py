"""Endpoint HTTP của miền báo cáo.

  POST /reports        xin sinh một báo cáo  -> trả job_id ngay
  GET  /reports/{id}   đọc báo cáo đã sinh
  GET  /jobs/{id}      hỏi job chạy tới đâu

Controller chỉ làm 4 việc: nhận, validate, gọi pipeline, trả response.
Không câu SQL, không gọi LLM, không if/else nghiệp vụ.

Không tự chạy pipeline tới cùng: sinh báo cáo mất vài phút nên pipeline đẩy
việc vào jobs/ rồi trả job_id. Client hỏi lại sau.
"""
