"""Dịch sự kiện thô của provider sang sự kiện miền của Mycel.

Mỗi provider gọi tên sự kiện một kiểu. Quy về một bộ tên chung ở đây, nên đổi model
không làm vỡ client: `token`, `tool_started`, `tool_finished`, `agent_switched`,
`error`, `done`.
"""
