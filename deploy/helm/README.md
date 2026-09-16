# Helm — deploy tái lập được

## Vấn đề nó giải

Viết tay YAML cho K8s thì mỗi môi trường một bản sao, sửa một chỗ quên hai chỗ,
và không ai nói được "prod đang chạy đúng cấu hình nào". Helm đóng gói toàn bộ
thành một chart có version: cùng chart + `values-prod.yaml` luôn ra cùng kết quả.

## Cấu trúc

```
deploy/helm/mycel/
  Chart.yaml            tên, version chart, version app
  values.yaml           mặc định — đủ chạy, không hợp với môi trường nào
  values-staging.yaml   đè lên mặc định
  values-prod.yaml      đè lên mặc định
  templates/
    api/                Deployment, Service, HPA, Ingress
    worker/             Deployment, HPA (theo Kafka lag)
    scheduler/          Deployment (luôn replicas: 1 — xem bên dưới)
    vllm/               Deployment + GPU, chỉ bật khi values cho phép
    stateful/           Postgres, Kafka, Qdrant, MinIO
    observability/      collector, Tempo, Prometheus, Loki, Grafana
```

## Hai version, đừng nhầm

| | Nghĩa | Đổi khi |
|---|---|---|
| `version` | version của chart | sửa template hay values |
| `appVersion` | commit SHA của image | build image mới |

Deploy code mới mà không sửa manifest thì chỉ `appVersion` đổi. Rollback chart
không tự rollback code, và ngược lại — nên luôn ghi cả hai vào log release.

## `scheduler` luôn một replica

Hai scheduler cùng chạy thì mỗi lịch bắn hai lần: hai lần sync, hai báo cáo trùng.
Idempotency key ở `queue/job.py` đỡ được phần lớn hậu quả, nhưng đúng cách vẫn là
không chạy hai cái. Đặt `replicas: 1` và `strategy: Recreate` — `RollingUpdate` dựng
pod mới **trước** khi xoá pod cũ, tức là có một khoảng hai scheduler cùng sống.

## Secret không nằm trong values

`values-prod.yaml` nằm trong git. Mật khẩu Postgres, API key cloud LLM thì không.
Chart chỉ tham chiếu tên của `Secret`; giá trị nạp riêng (sealed-secrets hoặc Vault).

## Chạy

```bash
helm upgrade --install mycel deploy/helm/mycel \
  -f deploy/helm/mycel/values-prod.yaml \
  --set image.tag=$GIT_SHA

helm diff upgrade ...   # xem trước thay đổi, nên chạy trước mọi lần deploy
helm rollback mycel     # về release trước
```

Thực tế thì Argo CD chạy những lệnh này, không phải người — xem `deploy/argocd/`.

## Migration vẫn chạy trước

Helm không biết thứ tự này, phải khai bằng `pre-upgrade` hook chạy
`alembic upgrade head`. Hook fail thì Helm dừng, pod mới không lên. Vẫn giữ quy
tắc tương thích ngược một bậc: pod cũ còn sống trong lúc migration chạy.
