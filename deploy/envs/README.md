# Environments

One image everywhere. Environments differ only in environment variables and secrets —
there is no `if env == "prod"` branch anywhere in the code.

| | Runs on | Stores | What runs it |
|---|---|---|---|
| **dev** | a developer's machine | Postgres, RabbitMQ, Redis in compose | `scripts/stack.sh dev up` |
| **dev, on a cluster** | minikube on that same machine | the same compose stores, reached at `host.minikube.internal` | `helm upgrade --install` |

**There is no staging and no prod**, and this file used to describe both. Writing them down
before they exist produces documentation that is confidently wrong — which is harder to
notice than documentation that is missing, because it reads as a system somebody built.
`values-staging.yaml` and `values-prod.yaml` were deleted for the same reason; see
`deploy/helm/README.md`.

What the cluster path proves today is that the chart runs. What it does not have is a
cluster anyone else can reach, which is also why CI renders the chart rather than deploying
it — see `.github/workflows/release.yml`.

## Deploying, with compose

```bash
docker compose pull                                 # the image CI built, by SHA
docker compose run --rm api alembic upgrade head    # migrations FIRST
docker compose up -d                                # then swap the containers
```

## Deploying, on the cluster

The ordering is the same and the chart does it: `alembic upgrade head` runs as a
`pre-install,pre-upgrade` hook, so Helm stops before the new pods start if it fails.

```bash
helm upgrade --install mycel deploy/helm/mycel \
  -f deploy/helm/mycel/values-minikube.yaml \
  --set image.tag=$GIT_SHA
```

**Either way, every schema change must be backward compatible by one step** — the old code
is still serving while the migration runs. Dropping a column takes two releases: remove the
code that reads it, then drop it.

## Rollback

Images are tagged by commit SHA, so going back is changing the tag. Migrations do not roll
back on their own, which is the whole reason for the one-step rule above.

On the chart, `helm rollback` returns the *templates* to a previous release — it does not
return the code, because the code is `appVersion` and the image tag. Rolling back a bad
deploy means both.

## Secrets

Not in the repo, not in the image, read from the environment at runtime. On the cluster
they are one Secret created outside Helm:

```bash
kubectl create secret generic mycel-secrets --from-env-file=.env
```

`.env.example` lists every variable that must exist and never holds a real value. Two
things to re-read before applying that command: the four `*_URL` values must name
`externalStores.host` rather than `localhost` — inside a pod, `localhost` is that pod — and
the Secret carries the whole file, so a setting in it overrides the ConfigMap. That second
one cost a debugging round; `templates/_helpers.tpl` records it.
