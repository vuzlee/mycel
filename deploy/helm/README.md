# Helm — reproducible deploys

## The problem it solves

Hand-written K8s YAML means one copy per environment, edits applied in one place and
forgotten in two others, and nobody able to say "the cluster is running exactly this
configuration". Helm packs the whole thing into a versioned chart: the same chart plus
`values-<env>.yaml` always produces the same result.

## Layout

```
deploy/helm/mycel/
  Chart.yaml              chart name, chart version, app version
  values.yaml             defaults — enough to run, right for no environment
  values-minikube.yaml    the one that is actually run
  values-staging.yaml     a cluster that does not exist yet
  values-prod.yaml        a cluster that does not exist yet
  templates/
    _helpers.tpl          names, labels, the shared envFrom
    configmap.yaml        settings that are not keys
    secret.yaml           NOT a manifest — how to create the Secret, and why
    api/                  Deployment, Service, Ingress
    worker/               Deployment
    scheduler/            Deployment (always replicas: 1 — see below)
    hooks/migrate.yaml    pre-install,pre-upgrade: alembic upgrade head
```

Seven manifests. No HPA, no StatefulSet, no vllm, no observability — see
`deploy/kubernetes/README.md` for what each of those would cost and why none is here yet.
Batch 058 adds `monitoring/`.

## Two versions, do not mix them up

| | Means | Changes when |
|---|---|---|
| `version` | the chart's version | templates or values change |
| `appVersion` | the image's commit SHA | a new image is built |

Deploying new code without touching manifests changes only `appVersion`. Rolling back the
chart does not roll back the code, and vice versa — so record both.

## `scheduler` is always one replica

Two schedulers means every schedule fires twice. `RollingUpdate` starts the new pod
**before** removing the old one, which is exactly that window. `replicas: 1` and
`strategy: Recreate`.

## Secrets do not live in values

`values-*.yaml` is in git. The Postgres password and the provider keys are not. The chart
references a `Secret` by name and renders none — `helm template` on this chart produces no
credential of any kind, which is the property worth keeping.

```bash
kubectl create secret generic mycel-secrets --from-env-file=.env
```

Then re-read the four URLs in it: `DATABASE_URL`, `RABBITMQ_URL`, `REDIS_URL` and
`REDIS_CACHE_URL` must name `externalStores.host`, not `localhost`. Inside a pod,
`localhost` is that pod.

## Running it on minikube

```bash
minikube start --driver=docker
minikube addons enable ingress

docker build -t mycel:dev .
minikube image load mycel:dev          # no registry involved

kubectl create secret generic mycel-secrets --from-env-file=.env
helm upgrade --install mycel deploy/helm/mycel -f deploy/helm/mycel/values-minikube.yaml

minikube tunnel                        # then mycel.local resolves via /etc/hosts
```

`helm template` renders without touching a cluster, and is the fastest way to see what a
values change actually does.

## Migrations run first

Helm does not infer this ordering; it is declared with a `pre-install,pre-upgrade` hook
running `alembic upgrade head`. **Both** events matter: `pre-upgrade` alone means the first
`--install` never migrates and all three pods start against an empty database. If the hook
fails Helm stops and the new pods never start, which only holds while migrations stay
backward compatible for one step.
