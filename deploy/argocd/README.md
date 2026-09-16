# Argo CD — GitOps

## Vấn đề nó giải

Deploy bằng tay (`helm upgrade` từ máy ai đó) thì không ai trả lời được hai câu:
*prod đang chạy đúng cái gì* và *ai đổi lúc nào*. Argo CD lật ngược chiều: git là
nguồn sự thật duy nhất, Argo so cụm với git rồi tự kéo cho khớp.

```
git push ──► CI: lint · test · build image (tag = SHA) ──► push lên Harbor
                                                              │
             CI sửa image.tag trong values ◄──────────────────┘
                     │
                     └─► commit vào repo config
                                │
                     Argo CD thấy git đổi ──► helm upgrade vào cụm
```

CI **không** có quyền vào cụm. Nó chỉ build image và sửa một dòng trong git.
Credential của cụm nằm ở Argo, không nằm trong CI.

## Vì sao tách repo config

`image.tag` đổi mỗi lần build. Để chung repo code thì CI commit vào chính repo đó
và kích hoạt lại CI — vòng lặp. Hai cách thoát:

| | |
|---|---|
| Repo config riêng | sạch nhất, nhưng thêm một repo phải đồng bộ |
| Cùng repo, CI bỏ qua commit của chính nó (`[skip ci]`) | đơn giản hơn, dễ quên |

Dự án đang dùng **cùng repo**, thư mục `deploy/helm/`, CI đánh dấu `[skip ci]`.

## Auto-sync và chỗ cần cẩn thận

| Tuỳ chọn | Làm gì | Rủi ro |
|---|---|---|
| `automated.prune` | xoá tài nguyên không còn trong git | xoá nhầm PVC → mất dữ liệu |
| `automated.selfHeal` | ai đó `kubectl edit` thì Argo ghi đè lại | mất đường vá nóng khi sự cố |

Đặt `prune: false` cho mọi thứ có state (Postgres, Kafka, Qdrant, MinIO), hoặc gắn
`Prune=false` lên từng tài nguyên đó. Ghi nhầm một dòng trong values rồi Argo prune
mất PVC của Postgres là kiểu tai nạn không rollback được bằng git.

**Staging tự sync, prod cần người bấm.** Prod để `syncPolicy` thủ công hoặc bật
sync window — deploy vào 5 giờ chiều thứ Sáu không phải việc của máy.

## Migration và sync wave

Argo áp dụng manifest theo `sync-wave`, số nhỏ trước:

| Wave | Gì |
|---|---|
| `-1` | Job migration (`alembic upgrade head`) — hook `PreSync` |
| `0` | Deployment api, worker, scheduler |

Migration fail thì sync dừng, pod cũ vẫn chạy. Vẫn giữ quy tắc schema tương thích
ngược một bậc: có một khoảng code cũ chạy với schema mới.

## File

```
application-staging.yaml   Application: theo dõi deploy/helm, values-staging, auto-sync
application-prod.yaml      Application: values-prod, sync thủ công
project.yaml               AppProject: giới hạn repo và namespace được phép đụng
```
