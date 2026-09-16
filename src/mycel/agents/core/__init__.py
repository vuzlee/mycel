"""Nền chung của riêng `agents/`: khung chạy agent, phần không dính nghiệp vụ.

Cùng khuôn với `mycel/core/` nhưng hẹp hơn một tầng — cái kia là nền chung của toàn hệ.

Tách khỏi các agent cùng cấp trên (`orchestrator.py`, `analyst.py`...) vì hai thứ đổi với
nhịp khác nhau: cách stream token hay cách gắn trace gần như không đổi, còn prompt thì đổi
liên tục. Lẫn vào nhau thì mỗi lần sửa prompt phải đọc lại code streaming.

  agent.py         vòng chạy: message -> model -> tool -> output
  run_context.py   thứ một lượt chạy mang theo: job_id, budget, session DB, trace
  config.py        chọn model, tham số sinh, giới hạn vòng lặp
  model_builder.py spec '<tier>:<model_name>' -> client đã sẵn sàng gọi
  schemas.py       hợp đồng nội bộ giữa agent, tool và streaming
  hooks.py         trước/sau mỗi run: gắn trace, log usage, cộng budget
  guards.py        chặn vòng lặp vô hạn, model lặp chính nó, output sai schema
  exceptions.py    lỗi của khung
  streaming/       trả kết quả dần
  integrations/    nối với tool và agent bên ngoài

Không import ngược lên các agent hay `tools/` — chiều phụ thuộc một hướng.
"""
