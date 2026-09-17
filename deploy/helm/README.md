# Helm — reproducible deploys

## The problem it solves

Hand-written K8s YAML means one copy per environment, edits applied in one place and forgotten
in two others, and nobody able to say "prod is running exactly this configuration". Helm packs
the whole thing into a versioned chart: the same chart + `values-prod.yaml` always produces the
same result.

## Layout

```
deploy/helm/mycel/
  Chart.yaml            chart name, chart version, app version
  values.yaml           defaults — enough to run, right for no environment
  values-staging.yaml   overrides the defaults
  values-prod.yaml      overrides the defaults
  templates/
    api/                Deployment, Service, HPA, Ingress
    worker/             Deployment, HPA (on Kafka lag)
    scheduler/          Deployment (always replicas: 1 — see below)
    vllm/               Deployment + GPU, only when values enable it
    stateful/           Postgres, Kafka, Qdrant, MinIO
    observability/      collector, Tempo, Prometheus, Loki, Grafana
```

## Two versions, do not mix them up

| | Means | Changes when |
|---|---|---|
| `version` | the chart's version | templates or values change |
| `appVersion` | the image's commit SHA | a new image is built |

Deploying new code without touching manifests changes only `appVersion`. Rolling back the chart
does not roll back the code, and vice versa — so always record both in the release log.

## `scheduler` is always one replica

Two schedulers running means every schedule fires twice: two syncs, two duplicate reports. The
idempotency key in `queue/job.py` absorbs most of the damage, but the correct fix is still not
running two. Set `replicas: 1` and `strategy: Recreate` — `RollingUpdate` starts the new pod
**before** removing the old one, which means a window with two live schedulers.

## Secrets do not live in values

`values-prod.yaml` is in git. The Postgres password and the cloud LLM API key are not. The chart
only references `Secret` names; the values are loaded separately (sealed-secrets or Vault).

## Running it

```bash
helm upgrade --install mycel deploy/helm/mycel \
  -f deploy/helm/mycel/values-prod.yaml \
  --set image.tag=$GIT_SHA

helm diff upgrade ...   # preview the change, worth running before every deploy
helm rollback mycel     # back to the previous release
```

In practice Argo CD runs these commands, not a person — see `deploy/argocd/`.

## Migrations still run first

Helm does not know about this ordering; it has to be declared with a `pre-upgrade` hook running
`alembic upgrade head`. If the hook fails Helm stops and the new pods never start. The one-step
backward-compatibility rule still holds: the old pods are alive while the migration runs.
