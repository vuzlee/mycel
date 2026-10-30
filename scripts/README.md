# scripts/

```
stack.sh   the one command; dispatches only
lib/       shared by the modes (common.sh) and by dev/ (hostproc.sh)
dev/       app on the host, stores in compose
compose/   everything in containers
k8s/       the chart on minikube
ops/       doctor, sync, load; no mode
```

| Mode | api · worker · scheduler · ingest | Stores | Use it for |
|---|---|---|---|
| `dev` | host, `uv run` | compose | writing code |
| `compose` | containers, the image | compose | checking the image CI builds |
| `k8s` | pods on minikube | compose | checking the chart |

Stores stay in compose in every mode.

## k8s secret

`localhost` inside a pod is that pod. `k8s/secret.sh` builds the Secret from `.env` and
rewrites the store URLs to `host.minikube.internal`. Use it instead of
`kubectl create secret --from-env-file`.

## doctor

Works with no `.env`. Writes nothing. Exits 1 on BROKEN, 0 when everything is running or
deliberately off.

## load

`stack.sh load [compose|k8s] [rates] [seconds] [routes]`: signed-in reads under k6 in docker at a
fixed arrival rate, one step per rate, stopping at the first that breaks the SLO (p95 < 300 ms,
p99 < 1 s, errors < 0.1%; `SLO_P95`, `SLO_P99`, `SLO_ERRORS` override). Prints one row per step
and the capacity: the last rate that held. Each step runs `RUNS` (3) times and holds only if all do.
Writes a session for the first user and deletes it on exit.

`stack.sh load seed [users]` builds `mycel_load` (2,000 users, 1 M turns, 50k work items), moves the
api onto it and pins api, Postgres and k6 to their own cores; runs then sign in as many users.
`stack.sh load reset` puts the api back on the dev database. The seed refuses any other database.
No route in the default mix calls a model.
