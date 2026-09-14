# Evals

Test thường bắt lỗi code. Eval bắt lỗi **chất lượng** — báo cáo không sai cú pháp,
chỉ là kém hơn bản trước. Không có eval thì đổi prompt là đoán mò.

## Golden set

`golden/` chứa các cặp *đầu vào → đầu ra mong đợi* lấy từ ca thật:

```
golden/
  weekly-summary-01.yaml    # dữ liệu gold mẫu + báo cáo con người chấp nhận được
```

Mỗi lần đổi prompt, đổi model, hay nâng version agent: chạy lại toàn bộ golden set,
so điểm với lần chạy trước.

## Chấm điểm

| Loại | Chấm thế nào |
|---|---|
| Có cấu trúc | So trực tiếp — trích đúng số liệu, đúng ngày, đúng tên |
| Văn xuôi | LLM chấm theo rubric, kèm người xem lại mẫu ngẫu nhiên |

Ghi điểm từng lần chạy để thấy xu hướng. Một bản prompt làm điểm tụt là chặn merge,
không phải để bàn cảm tính.
