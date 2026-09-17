# Kubernetes — on-premise

The whole stack runs on a self-hosted cluster, with no dependency on any cloud.

## What Compose and Kubernetes are each for

| | Runs on | Used for |
|---|---|---|
| `docker-compose.yml` | a developer's machine | writing code, debugging, trying things out |
| `deploy/helm/` | the on-prem K8s cluster | staging, prod |

Two different files, but the **same image** and the same set of environment variables. There is
no `if env == "prod"` branch in the code.

## Standing up a cluster

With no cluster yet, pick one of two:

| | Suits |
|---|---|
| **k3s** | 1–3 physical machines. One binary, ingress and local-path storage included |
| **kubeadm** | multi-node clusters where every component needs to be controlled |

This project targets **k3s**: enough for a few nodes, and less to maintain.

## Why K8s rather than compose on a real host

Four things compose cannot do — and the same four requirements at the bottom of the list:

| Requirement | How K8s does it |
|---|---|
| The API can scale | `Deployment.replicas` — many pods behind one Service |
| A dead pod comes back | kubelet restarts the container; the Deployment recreates a lost pod |
| More traffic adds pods | `HorizontalPodAutoscaler` on CPU or a custom metric |
| Services can reach each other | `Service` — one stable DNS name, load-balanced already |

`docker compose up -d` can restart a dead container, but it cannot move the work to another
machine when the **machine** dies, and it does not scale with load.

## Self-healing only works when the probes are right

A hung pod that still has its port open looks healthy to K8s — no restart, and the Service keeps
sending requests to it. So every service must declare:

| Probe | Answers | On failure |
|---|---|---|
| `readinessProbe` | can it take requests yet | pulled from the Service, pod stays alive |
| `livenessProbe` | is it still recoverable | container restarted |
| `startupProbe` | has it finished booting | delays the other two |

`startupProbe` matters for `vllm`: loading the model takes minutes, and without it liveness
kills the pod before it is ever ready, forever.

## HPA: a different measure per service

| Service | Scales on | Why not CPU |
|---|---|---|
| `api` | CPU | the right kind of load: many small requests |
| `worker` | **Kafka consumer lag** | workers wait on I/O, CPU stays low while the queue backs up |
| `vllm` | **no autoscaling** | each pod holds a GPU; with no free GPU an extra pod only sits Pending |

Scaling `worker` on lag needs an external metric, via KEDA or prometheus-adapter.

**Hard ceiling:** actual working workers = min(replicas, partition count). With a 6-partition
topic, an HPA pushing to 10 pods still leaves only 6 with work — see `KAFKA_NUM_PARTITIONS` in
`docker-compose.yml`. Set `maxReplicas` to the partition count.

## Where the stateful services run

Postgres, Kafka, Qdrant and MinIO all hold data. In the cluster they run as `StatefulSet` +
`PersistentVolumeClaim`, **not** `Deployment`: they need a stable identity and a volume that
reattaches to the same pod after a restart.

On-prem means providing the storage layer yourself (k3s local-path, or Longhorn if a pod's
volume should be able to follow it to another machine). This is the most labour-intensive part
of leaving the cloud.
