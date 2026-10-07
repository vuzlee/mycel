# Kubernetes — what actually runs

The three application processes run as pods. The stores do not.

## Compose and Kubernetes, and the same image

| | Runs on | Used for |
|---|---|---|
| `docker-compose.yml` | a developer's machine | writing code, debugging, the stores |
| `deploy/helm/` | minikube today, a real cluster later | proving the chart |

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

`worker` and `scheduler` have a **liveness probe on `/metrics`** and no readiness probe.
057 gave them neither and recorded it as debt; 058 built the thing that asks `/metrics` and
settled it.

A partly hung process does still answer, which is what 057 said. But one killed for memory,
or deadlocked in its whole loop, does not — and that is the half kubelet catches. The other
half, a port open while no job runs, no probe can catch: from outside it is identical to an
idle worker, and it belongs to an alert on the failed-job count.

No readiness probe, because nothing sends requests to a worker. "Can it take work yet" is a
question about a Service's endpoint list, and a worker is in no Service.

**`METRICS_HOST` is set on the container, not in the ConfigMap.** The Secret is created
from the whole of `.env`, and `secretRef` is listed after `configMapRef` in `envFrom`, so
it wins every collision: a developer's `127.0.0.1` — correct on a laptop, where it is what
keeps an unauthenticated port private — replaced the `0.0.0.0` the cluster needs, and the
probe got connection refused. `env:` on the container outranks both.

## What measures it

`--set monitoring.enabled=true` adds four more pods: Prometheus, Loki, Promtail and
Grafana. Off by default, the way compose keeps them behind `profiles: [monitoring]`.

| Pod | Does what |
|---|---|
| `prometheus` | asks each process every 15s how it is doing |
| `promtail` | DaemonSet — reads pod log files off each node and pushes them |
| `loki` | holds what Promtail pushes |
| `grafana` | the screen, on its own hostname |

Two things differ from the compose versions, and the second is not a config change.
Prometheus asks the cluster which pods are alive instead of naming three addresses, so a
replaced pod costs no edit. Promtail cannot use `docker.sock` — a pod has no docker — so it
reads `/var/log/pods` directly, and runs one copy per node because a container's log is a
file on the disk of the machine running it.

No operator. `ServiceMonitor` needs a resident program to read it; a scrape config in a
ConfigMap can be read by eye. That trade flips when a second team adds services of its own.

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
