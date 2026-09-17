# Environments

Three environments, one image. They differ only in environment variables and secrets — there
is no `if env == "prod"` branch anywhere in the code.

| | Runs on | Database | LLM |
|---|---|---|---|
| **dev** | A developer's machine | Postgres in compose | cloud, or local vLLM with a GPU |
| **staging** | One host | Its own Postgres, anonymised data | cloud, own rate-limited key |
| **prod** | Real hosts | Postgres with backups | cloud, own key |

## Deploying

```bash
docker compose pull            # pull the image CI built, by SHA
docker compose run --rm api alembic upgrade head   # migrations FIRST
docker compose up -d           # then swap the containers
```

This order matters: migrations run before the new code goes live, so every schema change must
be **backward compatible by one step** — the old code must still work against the new schema.
Dropping a column takes two releases: first remove the code using it, then drop it.

## Rollback

Images are tagged by commit SHA, so going back a version is changing the tag and running
`up -d`. Migrations do not roll back on their own — which is why backward compatibility is
required.

## Secrets

Not in the repo, not in the image. Read from environment variables at runtime.
`.env.example` lists the variable names that must exist, and never holds real values.
