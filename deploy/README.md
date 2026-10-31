# deploy/

```
helm/mycel/     the chart: api, worker, scheduler, ingest, migrate hook, monitoring
helm/mycel-stores/  the stores in the cluster, for stores-up and EKS
helm/mycel/files/   Grafana and Loki config, also mounted by compose
monitoring/     Prometheus, Alertmanager and Alloy config for compose
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

| Setup | Pods | Stores |
|---|---|---|
| `k8s up` (minikube) | api · worker · scheduler · ingest | compose on the host, at `externalStores.host` (`host.minikube.internal`) |
| `k8s stores-up` (minikube, later EKS) | the same, `values-aws.yaml` | in the cluster, chart `helm/mycel-stores/`, one Service per store, `emptyDir` |

`stores-up` installs the stores first (the migrate hook needs Postgres), makes the app's
gateway key, then the app. Every pod pulls with one Docker Hub login when `.env` has
`DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`. Plan: `docs/plan/aws-phase-1.html`.

## Rules

| Rule | Why |
|---|---|
| Create the Secret with `scripts/stack.sh k8s secret` | `localhost` inside a pod is that pod; the script rewrites the store URLs |
| Settings that must hold go in the container `env:` | the Secret carries all of `.env` and overrides the ConfigMap |
| Every pod has `enableServiceLinks: false` | a Service named `rabbitmq` would inject `RABBITMQ_PORT=tcp://…` and break Settings |
| The Secret needs `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` | tracing is on: without the keys every pod refuses to start (`ConfigError`) |
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
Alloy and Grafana. In the cluster Prometheus discovers pods and Alloy is a DaemonSet
reading `/var/log/pods`. Data is not persisted.
