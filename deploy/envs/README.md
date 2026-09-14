# Môi trường

Ba môi trường, cùng một image. Khác nhau chỉ ở biến môi trường và secret —
không có nhánh `if env == "prod"` nào trong code.

| | Chạy ở | Database | LLM |
|---|---|---|---|
| **dev** | Máy lập trình viên | Postgres trong compose | cloud, hoặc vLLM local nếu có GPU |
| **staging** | Một host | Postgres riêng, dữ liệu ẩn danh | cloud, key riêng có hạn mức |
| **prod** | Host thật | Postgres có backup | cloud, key riêng |

## Deploy

```bash
docker compose pull            # lấy image đã build ở CI theo SHA
docker compose run --rm api alembic upgrade head   # migration TRƯỚC
docker compose up -d           # rồi mới đổi container
```

Thứ tự này quan trọng: migration chạy trước khi code mới lên, nên mọi thay đổi
schema phải **tương thích ngược một bậc** — code cũ vẫn chạy được với schema mới.
Muốn xoá một cột thì làm hai lần release: lần đầu bỏ code dùng nó, lần sau mới drop.

## Rollback

Image tag theo commit SHA nên quay về bản trước là đổi tag rồi `up -d`. Migration
thì không tự lùi — đó là lý do phải giữ tương thích ngược.

## Secret

Không nằm trong repo, không nằm trong image. Đọc từ biến môi trường lúc chạy.
`.env.example` liệt kê tên biến cần có, không bao giờ chứa giá trị thật.
