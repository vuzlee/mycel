# deploy/

```
helm/mycel/     the chart: api, worker, scheduler, ingest, migrate hook, monitoring
helm/mycel/files/   Grafana and Loki config, also mounted by compose
monitoring/     Prometheus and Promtail config for compose
inference/      local vLLM (planned, off)
```

One image everywhere. Environments differ only in variables and secrets.

## Run it on minikube

```bash
minikube start --driver=docker && minikube addons enable ingress
scripts/stack.sh k8s build              # mycel:dev and mycel-ingest:dev, loaded into the node
scripts/stack.sh k8s up [monitoring]    # Secret, then helm upgrade --install
minikube tunnel                         # mycel.local and grafana.mycel.local in /etc/hosts
```

`helm template deploy/helm/mycel -f deploy/helm/mycel/values-minikube.yaml` renders without a cluster.

## What runs where

| Pods | Stays in compose on the host |
|---|---|
| api · worker · scheduler · ingest | Postgres · RabbitMQ · Redis · Qdrant · MinIO · LiteLLM |

Pods reach the stores at `externalStores.host` (`host.minikube.internal`).

## Rules

| Rule | Why |
|---|---|
| Create the Secret with `scripts/stack.sh k8s secret` | `localhost` inside a pod is that pod; the script rewrites the store URLs |
| Settings that must hold go in the container `env:` | the Secret carries all of `.env` and overrides the ConfigMap |
| Migrations run as a `pre-install,pre-upgrade` hook | new pods never start on an old schema |
| Every migration is backward compatible by one step | the old code serves while it runs; drop a column in two releases |
| `scheduler`: `replicas: 1`, `strategy: Recreate` | two schedulers fire every schedule twice |
| Images tagged by commit SHA | rollback is a tag change; `helm rollback` alone does not roll back code |

## Probes

| Process | Liveness | Readiness |
|---|---|---|
| api | `/health/live` (process only) | `/health/ready` (Postgres) |
| worker · scheduler · ingest | `/metrics` | none: no Service sends them traffic |

## Monitoring

`--set monitoring.enabled=true` (compose: `--profile monitoring`) adds Prometheus, Loki,
Promtail and Grafana. In the cluster Prometheus discovers pods and Promtail is a DaemonSet
reading `/var/log/pods`. Data is not persisted.
