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

`stack.sh load [compose|k8s] [vus] [seconds] [routes]`: signed-in reads under k6 in docker,
one line per status. Writes a one-hour session for the first user and deletes it on exit.
No route in the default mix calls a model.
