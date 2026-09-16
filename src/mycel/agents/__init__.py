"""Tầng agent: orchestrator điều phối, mỗi agent chuyên một việc, tool là năng lực agent gọi được.

  core/            khung chạy — vòng lặp agent, streaming, hook trace/budget, MCP
  orchestrator.py  điều phối: chia task, giao việc, ghép kết quả
  analyst.py       phân tích số liệu
  writer.py        viết văn bản
  reviewer.py      đối chiếu với nguồn
  registry.py      khai báo agent và tool orchestrator được dùng
  tools/           năng lực agent gọi được: query_gold, chart, compute
  prompts/         prompt tách khỏi code

Agent chuyên một việc thì prompt ngắn, eval chấm được từng cái, hỏng cái nào biết ngay cái đó.
"""
