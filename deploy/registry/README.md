# Harbor — registry ảnh nội bộ

Cụm on-prem thì ảnh cũng phải ở trong nhà: không phụ thuộc Docker Hub, không đụng
rate limit, và ảnh chứa code nội bộ thì không đẩy lên registry công cộng.

## Ngoài chỗ chứa ảnh, Harbor cho thêm

| | Vì sao cần |
|---|---|
| Quét lỗ hổng (Trivy) | chặn đẩy ảnh có CVE nghiêm trọng, tự quét lại khi có CVE mới |
| Ký ảnh (Cosign) | cụm chỉ chạy ảnh CI ký — ai đó push tay thì không lên được |
| Proxy cache | `docker.io/postgres:16` kéo một lần, lần sau lấy trong nhà |
| Chính sách dọn | mỗi commit một tag, không dọn thì đĩa đầy trong vài tháng |
| RBAC + audit log | ai đẩy ảnh nào lúc nào |

Proxy cache là lý do thực dụng nhất: mọi image bên thứ ba trong `docker-compose.yml`
(postgres, kafka, qdrant, minio, grafana...) đều đi qua Harbor, nên cụm dựng lại
được kể cả khi mất mạng ra ngoài.

## Project

```
mycel/           ảnh của app, tag = commit SHA
dockerhub/       proxy cache của docker.io
ghcr/            proxy cache của ghcr.io
```

## Quy tắc tag

Tag = **commit SHA**, không bao giờ `latest`. `latest` khiến hai pod cùng manifest
chạy hai code khác nhau, và rollback thì không biết lùi về đâu.

## Cụm kéo ảnh thế nào

Harbor dùng TLS nội bộ, nên mọi node phải tin CA đó — thiếu bước này thì pod
`ImagePullBackOff` với lỗi chứng chỉ, không phải lỗi quyền. Credential nằm trong
`imagePullSecret` (`harbor-creds` trong `values.yaml`), tài khoản chỉ có quyền đọc:
CI đẩy ảnh, cụm chỉ kéo.

## Dựng

Harbor chạy ngoài stack app (compose riêng hoặc chart riêng), vì nó phải sống
trước khi cụm kéo được ảnh đầu tiên. Không đưa vào `docker-compose.yml` của dự án —
dev build ảnh tại chỗ, không cần registry.
