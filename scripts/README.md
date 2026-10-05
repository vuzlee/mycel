# scripts/

```
stack.sh        the one command — dispatches and nothing else
lib/            what the modes share
dev/            app on the host, stores in compose
compose/        everything in containers
k8s/            the chart on minikube
data/           talks to the data or the repo, not to a mode
smoke/          hand-run, real models, real money, no CI
tools/          one-off jobs: seed a board, grant a project, record a demo, try a document
```

## Why a directory per mode

This was one 372-line script. It worked, and the reason it was split is not length: every
mode shared one set of variables and one `case`, so a change to the Kubernetes path could
break the dev one by touching something both read. Now `k8s/up.sh` cannot reach into
`dev/`, and the only shared thing is `lib/`, which is deliberately small.

## The three modes

The application is identical in all three. What differs is where the processes run.

| | api · worker · scheduler | Stores | Use it for |
|---|---|---|---|
| `dev` | on the host, `uv run` | compose | writing code — an edit needs no rebuild |
| `compose` | in containers, the image | compose | checking the image CI builds |
| `k8s` | pods on minikube | **still compose** | checking the chart deploys |

**The stores never move**, including in `k8s`. A StatefulSet with a volume claim is the
painful part of Kubernetes — storage classes, a volume per pod identity — and it proves
nothing the chart is meant to prove.

## The one that goes wrong

`k8s/secret.sh`, and it is why that step is a script rather than a line in a README.

Inside a pod, `localhost` is **that pod**. A `DATABASE_URL` copied straight out of `.env`
looks completely correct and the pod dies with connection refused to itself. The script
rewrites the four store URLs to `host.minikube.internal` and warns if it did not find four.

A second trap in the same file: the Secret carries the whole of `.env`, settings as well as
keys, because `--from-env-file` does. In `envFrom` the Secret is listed after the ConfigMap,
so every value in it wins — which is how `METRICS_HOST=127.0.0.1`, right on a laptop, once
made every liveness probe fail in the cluster. Anything that must hold regardless lives in
the container's own `env:`.

## lib/

`common.sh` is sourced by everything: paths, `log`/`die`, `wait_for`, and the compose
helpers. `hostproc.sh` is sourced only by `dev/` — pid files, `spawn`, `reap`, `sweep` —
because compose and Kubernetes each have a supervisor and neither wants one.

`wait_for` is the piece worth keeping in one place. Ready means "answers a query", not "the
container is up": Postgres accepts TCP several seconds before it will serve one, and
alembic run in that window fails with a message about the database rather than about the
wait.

## data/

`doctor`, `sync`, `grants` and `grafana-sync` take no mode. They talk to the database or to the repo,
and both are the same whichever way the app happens to be running.

`doctor` is the first command somebody runs after cloning, so it has to work with **no
`.env` at all** — every setting has a default, and a bare checkout produces a report rather
than a traceback. It writes nothing: no table, no file, no edit to `.env`. That is also why
there is no setup screen; a screen has to store what it collects, and storing means
configuration lives in two places that can disagree.

It exits 1 on BROKEN and 0 when everything is either running or deliberately **off**, so it
can gate a deploy without failing a build for a feature nobody wanted.

`grafana-sync --check` runs in CI. The three Grafana files exist twice because Helm's
`.Files.Get` does not follow symlinks — it reads the link target as a string, so a
symlinked `datasources.yaml` renders a ConfigMap holding a path and Grafana starts cleanly
with no datasources at all. The check is there because drift is otherwise invisible until
somebody opens whichever copy was not updated.
