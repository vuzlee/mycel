# Kiến trúc Mycel

## Nguyên tắc

1. **Một chiều.** Dữ liệu chỉ chảy raw → silver → gold. Không tầng nào đọc ngược lên.
2. **Agent chỉ đọc gold.** Agent không bao giờ chạm raw/silver — gold là hợp đồng duy nhất.
3. **Thêm nguồn không sửa code cũ.** Một provider mới = một file trong `sources/`.
4. **Tên module = việc nó làm.** Không viết tắt, không tầng trừu tượng thừa.

## Ba tầng dữ liệu

| Tầng | Schema | Chứa gì | Ai ghi |
|---|---|---|---|
| **raw** | `raw` | Payload nguyên bản từ provider, chưa đụng vào. Giữ để replay được. | `sources/` |
| **silver** | `silver` | Đã chuẩn hoá schema, khử trùng lặp, ép kiểu, gắn timestamp thống nhất. | `pipeline/` |
| **gold** | `gold` | Bảng đã tổng hợp theo nghiệp vụ, sẵn sàng cho truy vấn và báo cáo. | `pipeline/` |

Giữ raw nguyên bản là điều quan trọng nhất: khi logic transform sai, ta chạy lại từ raw
thay vì phải gọi lại provider.

## Các module

### `core/`
Config đọc từ env/file, logger, exception gốc, kiểu dữ liệu dùng chung. Không import
module nào khác trong `mycel` — đây là tầng đáy.

### `storage/`
Engine và session Postgres, repository cho từng tầng. Mọi câu SQL nằm ở đây, không rải
rác trong pipeline hay agent.

### `sources/`
Mỗi provider một module: `sources/slack.py`, `sources/gmail.py`... Cùng một interface:
nhận khoảng thời gian cần sync, trả về bản ghi thô, ghi xuống `raw`. Không xử lý,
không làm sạch — việc đó của pipeline.

Cấu hình riêng của từng nguồn (endpoint, scope, rate limit) nằm ở `config/sources/`.

### `pipeline/`
Các bước biến đổi. Mỗi bước là một hàm thuần: đọc từ tầng dưới, ghi lên tầng trên,
idempotent — chạy lại hai lần cho cùng kết quả.

### `agents/`
- **manager** — nhận yêu cầu báo cáo, chia nhỏ thành task, giao cho worker, ghép kết quả.
- **worker** — agent chuyên một việc (phân tích số liệu, viết tóm tắt, đối chiếu nguồn).
- **tools/** — năng lực agent gọi được: truy vấn gold, tính toán, dựng biểu đồ.

### `reports/`
Từ kết quả agent dựng ra artifact cuối: báo cáo văn bản, bảng số liệu, dashboard.

### `scheduler/`
Định nghĩa job và lịch chạy: sync nguồn theo giờ, transform sau khi sync xong, sinh
báo cáo hàng ngày/tuần.

### `api/`
Endpoint để trigger job thủ công, đọc báo cáo đã sinh, health check.

## Thứ tự phụ thuộc

```
core  ◄── storage ◄── sources
              ▲   ◄── pipeline
              │
           agents ◄── reports
              ▲
      scheduler, api
```

Mũi tên là "được import bởi". `core` không phụ thuộc gì; `api` và `scheduler` ngồi trên cùng.

## Mở rộng sau này

Khi một module phình to thì tách thành thư mục, giữ nguyên tên:
`sources/slack.py` → `sources/slack/{client.py,parser.py}`. Không cần dựng sẵn tầng
`domain/application/infrastructure` khi chưa có gì để bỏ vào.
