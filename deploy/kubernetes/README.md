# Kubernetes — on-premise

Toàn bộ stack chạy trên cụm tự dựng, không phụ thuộc cloud nào.

## Compose và Kubernetes dùng để làm gì

| | Chạy ở | Dùng khi |
|---|---|---|
| `docker-compose.yml` | máy lập trình viên | code, debug, chạy thử |
| `deploy/helm/` | cụm K8s on-prem | staging, prod |

Hai file khác nhau nhưng **cùng một image** và cùng một bộ biến môi trường. Không
có nhánh `if env == "prod"` trong code.

## Dựng cụm

Chưa có cụm thì chọn một trong hai:

| | Hợp với |
|---|---|
| **k3s** | 1–3 máy vật lý. Một binary, kèm sẵn ingress và local-path storage |
| **kubeadm** | cụm nhiều node, cần kiểm soát từng thành phần |

Dự án đang nhắm **k3s**: đủ cho vài node, và ít thứ phải bảo trì.

## Vì sao cần K8s chứ không phải compose trên host thật

Bốn thứ compose không làm được, và cũng là bốn dòng cuối trong bảng yêu cầu:

| Cần | K8s làm bằng |
|---|---|
| API scale được | `Deployment.replicas` — nhiều pod sau một Service |
| Pod chết thì tự sống lại | kubelet restart container; Deployment dựng lại pod mất hẳn |
| Traffic tăng thì tự thêm pod | `HorizontalPodAutoscaler` theo CPU hoặc metric tuỳ chỉnh |
| Service gọi nhau | `Service` — một DNS name ổn định, load-balance sẵn |

`docker compose up -d` restart container chết được, nhưng không dời việc sang máy
khác khi **máy** chết, và không tự tăng giảm theo tải.

## Self-healing chỉ hoạt động khi probe đúng

Pod treo mà vẫn mở cổng thì K8s coi là khoẻ — không restart, và Service vẫn đẩy
request vào đó. Nên mỗi service phải khai:

| Probe | Trả lời câu | Fail thì |
|---|---|---|
| `readinessProbe` | nhận request được chưa | rút khỏi Service, pod vẫn sống |
| `livenessProbe` | còn cứu được không | restart container |
| `startupProbe` | khởi động xong chưa | hoãn hai probe trên |

`startupProbe` quan trọng với `vllm`: nạp model mất vài phút, không có nó thì
liveness giết pod trước khi nó kịp sẵn sàng, lặp mãi.

## HPA: mỗi service một cách đo

| Service | Scale theo | Vì sao không theo CPU |
|---|---|---|
| `api` | CPU | đúng loại tải: nhiều request nhỏ |
| `worker` | **consumer lag của Kafka** | worker ngồi chờ I/O, CPU thấp trong khi hàng đợi dồn |
| `vllm` | **không autoscale** | mỗi pod giữ một GPU; không có GPU rảnh thì thêm pod cũng chỉ Pending |

Scale `worker` theo lag cần metric ngoài, lấy qua KEDA hoặc prometheus-adapter.

**Trần cứng:** số worker chạy thật = min(replica, số partition). Topic 6 partition
thì HPA đẩy lên 10 pod cũng chỉ 6 pod có việc — xem `KAFKA_NUM_PARTITIONS` trong
`docker-compose.yml`. Đặt `maxReplicas` bằng số partition.

## Stateful chạy ở đâu

Postgres, Kafka, Qdrant, MinIO đều giữ dữ liệu. Trong cụm thì chạy dạng
`StatefulSet` + `PersistentVolumeClaim`, **không** phải `Deployment`: cần danh tính
ổn định và volume gắn đúng pod cũ sau khi restart.

On-prem thì phải tự lo lớp storage (local-path của k3s, hoặc Longhorn nếu muốn
volume theo pod sang được máy khác). Đây là phần tốn công nhất khi bỏ cloud.
