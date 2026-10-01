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
  templates/
    _helpers.tpl          names, labels, the shared envFrom
    configmap.yaml        settings that are not keys
    secret.yaml           NOT a manifest — how to create the Secret, and why
    api/                  Deployment, Service, Ingress
    worker/               Deployment
    scheduler/            Deployment (always replicas: 1 — see below)
    hooks/migrate.yaml    pre-install,pre-upgrade: alembic upgrade head
    monitoring/           Prometheus, Loki, Promtail, Grafana — off by default
  files/                  the three Grafana files, copied; files/README.md says why
```

Seven manifests with monitoring off, twenty-six with it on. No HPA and no StatefulSet —
see `deploy/kubernetes/README.md` for what each would cost and why neither is here.

## Measuring and logs

`--set monitoring.enabled=true` adds Prometheus, Loki, Promtail and Grafana. Off by
default, the way compose keeps them behind `profiles: [monitoring]`: without it the chart
renders exactly the three application pods.

Prometheus asks the cluster which pods are alive rather than carrying a list of addresses,
so a replaced pod is found on the next refresh and nobody edits anything. That is the one
thing worth testing after a change: delete a worker and watch the target come back.

Promtail is a DaemonSet — one copy per node — because a container's log is a file on the
disk of the machine running it, and a collector on one node cannot read a file on another.

Both keep their data in the pod and lose it on a restart. Seven days of samples on a dev
box is not worth a volume claim that can get stuck `Pending` on the wrong storage class.

Grafana gets its own hostname (`grafana.mycel.local`) rather than a path under the api's,
because it serves assets from absolute paths.

## One environment file, and why there are not three

There were a `values-staging.yaml` and a `values-prod.yaml`. Both described a system that
had left: Kafka partitions, MinIO storage, autoscaling bounds — none of which any template
reads any more. They were harmless precisely because nothing read them, which is also why
they survived several batches of being wrong.

The cost was to the reader. Someone opening `values-prod.yaml` to learn what production
looks like found a Kafka cluster, and `values-minikube.yaml` — the one that runs — was the
third file down.

A values file is written when there is a cluster to write it for. `values.yaml` holds the
defaults and `values-minikube.yaml` shows the shape of an override; a staging file written
before staging exists is the same fiction one layer down.

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

With measuring and logs:

```bash
helm upgrade --install mycel deploy/helm/mycel \
  -f deploy/helm/mycel/values-minikube.yaml \
  --set monitoring.enabled=true
```

Both hostnames point at `minikube ip`, so `/etc/hosts` needs `mycel.local` and
`grafana.mycel.local` on that address.

`helm template` renders without touching a cluster, and is the fastest way to see what a
values change actually does.

## Migrations run first

Helm does not infer this ordering; it is declared with a `pre-install,pre-upgrade` hook
running `alembic upgrade head`. **Both** events matter: `pre-upgrade` alone means the first
`--install` never migrates and all three pods start against an empty database. If the hook
fails Helm stops and the new pods never start, which only holds while migrations stay
backward compatible for one step.
