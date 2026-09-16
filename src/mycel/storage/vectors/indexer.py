"""Từ gold sinh embedding rồi upsert vào Qdrant. Chạy nền, không chạy trong request.

Upsert theo id ổn định lấy từ khoá của bản ghi gold, nên chạy lại không sinh bản
trùng — cùng tinh thần idempotent với `etl/`.

Sinh embedding là việc khối lượng lớn, gọi theo lô: đúng loại việc để đẩy sang
model local (`llm/router.py` chọn tier LOCAL) thay vì đốt quota cloud.
"""
