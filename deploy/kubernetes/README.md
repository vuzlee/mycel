# Kubernetes — what actually runs

The three application processes run as pods. The stores do not.

## Compose and Kubernetes, and the same image

| | Runs on | Used for |
|---|---|---|
| `docker-compose.yml` | a developer's machine | writing code, debugging, the stores |
| `deploy/helm/` | minikube today, a real cluster later | proving the chart, then staging |

Two files, the **same image** and the same environment variables. There is no
`if env == "prod"` branch in the code — only a different `values-<env>.yaml`.

## minikube, and only minikube

Nothing here targets k3s or kubeadm. The chart is the same on any cluster; two things
differ and both live in values:

| | minikube | k3s |
|---|---|---|
| Ingress | `minikube addons enable ingress` installs nginx | Traefik ships with it |
| Reaching the api | `minikube tunnel`, or an entry in `/etc/hosts` | straight at the host |

`ingress.className` is the setting that carries the difference. Nothing is hardcoded, so
moving to a real cluster is a new values file, not a new chart.

**The image never goes through a registry.** `minikube image load mycel:dev` puts it in the
node's own docker daemon, and `pullPolicy: Never` stops the kubelet looking for a registry
that does not exist.

## Three pods, and what is deliberately not here

| Runs as a pod | Stays outside |
|---|---|
| `api` · `worker` · `scheduler` | Postgres · RabbitMQ · Redis |

The stores keep running under docker-compose on the host, reached at
`host.minikube.internal`. `StatefulSet` + `PersistentVolumeClaim` is the most
labour-intensive part of Kubernetes — storage classes, a volume per pod identity — and it
proves nothing the chart is meant to prove.

**`localhost` inside a pod is that pod.** A `DATABASE_URL` copied straight out of `.env`
looks perfectly correct and the pod dies with connection refused to itself. The four URLs
in the Secret have to name `externalStores.host`.

## Probes: two, not three, and only on the api

| Probe | Path | Why that path |
|---|---|---|
| `livenessProbe` | `/health/live` | touches nothing outside the process. A liveness probe that asks the database restarts healthy pods every time the database blinks |
| `readinessProbe` | `/health/ready` | does touch Postgres, and returns 503 rather than raising — a pod that cannot reach its database leaves the Service instead of dying |

No `startupProbe`: it exists to protect a process that takes minutes to boot, and uvicorn
does not.

`worker` and `scheduler` have **no probe at all**. They have no HTTP port, and `/metrics`
is not readiness — a process can serve metrics while doing no work. That is recorded as
debt; batch 058 builds the scrape and revisits it.

## Scaling: by hand, on purpose

`worker.replicas` is a number in values. There is no `HorizontalPodAutoscaler`, because
there is no load: an HPA on CPU is ten lines that mean nothing, and the measure that would
mean something is RabbitMQ queue depth through KEDA — a second control plane for a problem
nobody has.

The old ceiling does not apply here. RabbitMQ hands each message to one consumer, so
workers share a queue rather than being capped by a partition count.

## `scheduler` is always one

`RollingUpdate` starts the new pod **before** removing the old one, so every upgrade opens
a window with two live schedulers and every schedule fires twice. `strategy: Recreate` and
`replicas: 1`. The advisory lock in `domains/sync.py` absorbs most of the damage; not
running two is still the correct fix.
