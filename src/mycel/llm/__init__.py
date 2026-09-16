"""Tầng LLM: chọn model (local/cloud), gọi provider, cache, đếm token, chặn vượt trần chi phí.

  router.py   chọn tier cho mỗi lượt gọi
  client.py   nơi duy nhất import SDK provider
  providers/  khác biệt riêng của từng provider
  cache.py    prompt trùng thì không gọi lại
  tokens.py   đếm trước khi gửi
  usage.py    đếm sau khi gọi — nguồn số liệu cho budget, trace, log
  budget.py   trần chi phí theo job
"""
