# Argo CD — GitOps

## The problem it solves

Deploying by hand (`helm upgrade` from someone's machine) leaves two questions nobody can
answer: *what exactly is prod running* and *who changed it when*. Argo CD flips the direction:
git is the single source of truth, Argo compares the cluster against git and pulls it into
line.

```
git push ──► CI: lint · test · build image (tag = SHA) ──► push to Harbor
                                                              │
             CI edits image.tag in values ◄───────────────────┘
                     │
                     └─► commit to the config repo
                                │
                     Argo CD sees git change ──► helm upgrade into the cluster
```

CI has **no** access to the cluster. It only builds the image and edits one line in git.
Cluster credentials live in Argo, not in CI.

## Why a separate config repo

`image.tag` changes on every build. Keeping it in the code repo means CI commits to that same
repo and triggers CI again — a loop. Two ways out:

| | |
|---|---|
| Separate config repo | cleanest, but one more repo to keep in sync |
| Same repo, CI skips its own commits (`[skip ci]`) | simpler, easy to forget |

This project uses the **same repo**, directory `deploy/helm/`, with CI marking `[skip ci]`.

## Auto-sync and where to be careful

| Option | What it does | Risk |
|---|---|---|
| `automated.prune` | deletes resources no longer in git | deleting a PVC by mistake → data loss |
| `automated.selfHeal` | if someone runs `kubectl edit`, Argo overwrites it | no hot-patch route during an incident |

Set `prune: false` for anything with state (Postgres, Kafka, Qdrant, MinIO), or mark those
resources individually with `Prune=false`. Mistyping one line in values and having Argo prune
Postgres's PVC is the kind of accident git cannot roll back.

**Staging syncs itself, prod needs a human.** Leave prod on a manual `syncPolicy` or enable a
sync window — deploying at 5pm on a Friday is not a machine's decision.

## Migrations and sync waves

Argo applies manifests by `sync-wave`, lowest first:

| Wave | What |
|---|---|
| `-1` | Migration job (`alembic upgrade head`) — `PreSync` hook |
| `0` | api, worker and scheduler Deployments |

If the migration fails the sync stops and the old pods keep running. The one-step
backward-compatible schema rule still holds: there is a window where old code runs against the
new schema.

## Files

```
application-staging.yaml   Application: watches deploy/helm, values-staging, auto-sync
application-prod.yaml      Application: values-prod, manual sync
project.yaml               AppProject: limits which repos and namespaces may be touched
```
