# Mycel

A multi-agent system that turns the work already in your issue tracker into **progress
reports and dashboards**. Today it reads Jira; the source layer is pluggable.

Named after *mycelium*, the underground fungal network that connects a whole forest. Mycel
works the same way: running in the background, quietly gathering data, processing it through
several layers, and only then surfacing as a report.

> **Status:** the chain runs end to end — Jira to gold to a summary, a dashboard, a
> Telegram message and a calendar entry. `TELEGRAM_NOTIFY_CHAT_ID` is the one thing not
> yet exercised against a real chat.

## What it does

```
Jira ──► bronze ──► gold ──┬─► Summariser ──► Progress report ──► Telegram
         raw        ready  ├────────────────► Dashboard
                           └────────────────► due dates ──────► Google Calendar
```

Three surfaces, three jobs:

| | Role | Direction |
|---|---|---|
| **Jira** | the source of record for what the work is | read |
| **Telegram** | how a finished report reaches you | write |
| **Google Calendar** | deadlines on a phone | write |

Keep issues in Jira the way you already do. A scheduled sync pulls what moved, normalises
it into `gold.work_item` and `gold.worklog`, and two things read the result:

- **Progress report** — `POST /reports/summary` runs an agent over one project's window. It
  opens with a verdict (on track · at risk · off track) and a one-sentence headline, then the
  tables behind them: at risk, in flight, shipped, and estimated against spent per person.
  The agent fills columns — issue, title, epic, who, estimate, spent, due — rather than a sentence per line,
  so every surface renders the same rows without parsing prose. It lands in Postgres, so it is
  still there tomorrow, and the headline goes out to Telegram with a link back to it.
- **Dashboard** — `GET /dashboard/{project}` — numbers, no model call. One whole-project
  progress figure at the top, then the window: totals by status category, what is past due,
  the estimate-versus-spent gap per person, a progress bar per epic, and effort logged per day.
  The percentage is never drawn from the window — a quiet week is not a finished project.

Both outputs are one-way and optional; a deployment with neither still works. Mycel never
writes to your board, and never reads work back out of Calendar — an event has a start and
an end and nothing else, so anything read back would be a worse copy of what gold holds.

Effort curves come from worklogs, not resolution dates: Jira stamps a resolution with the
moment of the API call, so a back-filled project would draw a confident, false line.

The medallion layers live in one **PostgreSQL**, one schema each; agents read `gold` only.
A fourth schema, `app`, holds users, sessions and saved reports — it is product data, not
pipeline data, and does not inherit a pipeline grant.

Reasoning goes through `llm/` — high-volume work runs on a local model, final reasoning calls
a cloud model. No module imports a provider SDK directly.

## Running it

```bash
cp .env.example .env      # fill in DB and API keys
scripts/stack.sh up       # containers, migrations, api, worker, scheduler
```

One command, idempotent: it starts what is down, leaves what is up, applies migrations and
waits until each service answers a real query rather than merely accepting TCP.

| Command | What it does |
|---|---|
| `scripts/stack.sh up` | Bring the stack up (the default — bare `stack.sh` does this) |
| `scripts/stack.sh down` | Stop everything; named volumes keep the data |
| `scripts/stack.sh status` | What is running, on which port, with the dashboard URL |
| `scripts/stack.sh logs api` | Follow `api`, `worker` or `scheduler` |
| `scripts/stack.sh restart` | `down` then `up` — the usual way to pick up a code change |
| `scripts/stack.sh sync` | Run one Jira sync now, without waiting for the tick |
| `scripts/stack.sh relocate` | Move `mycel-pg` off an anonymous volume onto `mycel-pgdata`, keeping the data |
| `scripts/stack.sh restore <dump>` | Load a dump made by `relocate` (defaults to the newest in `.run/`) |

`down` stops the three host processes and the three containers; named volumes keep the
data, so `up` after it starts where you left off. Three Python processes run on the host —
`api`, `worker`, `scheduler` — and all three matter: without the worker both report
endpoints hand back a job id nobody picks up, and without the scheduler nothing syncs until
you run `sync` by hand.

`scripts/seed_jira.py` fills a fresh Jira project with the work this repository has done,
so the first sync does not read an empty board. Jira stamps `created` and every status
transition with the moment of the API call, so neither is back-dated and nothing downstream
claims to know how long an issue sat in a status; a worklog's `started` *is* settable, which
makes logged effort the one honest time series in a back-filled project. Every seeded issue
carries the label `backfill`.

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| UI | http://localhost:8000/app — sign in at `/app/login` |
| Dashboard | http://localhost:8000/app/dashboard |
| RabbitMQ | http://localhost:15672 |

Postgres is on **5433**, not 5432, so it cannot collide with a system install.

The stack script runs the API, the worker and the scheduler on the host under `uv run`,
because those are the ones being edited and a container would need rebuilding for each
change. The worker is not optional: without it both `POST /reports` endpoints return a job
id for work nobody ever picks up, which looks like a slow model rather than a missing
process.
Everything else is a container. `docker-compose.yml` still describes the full prod shape,
including Grafana, Prometheus and the local-LLM profile, for deployments that have the
compose CLI.

The UI is a separate build. `docker compose` does it for you; outside Docker, either build
it once (`cd web && npm ci && npm run build`, then it is served at `/app`) or run it in dev
mode (`npm run dev` on :5173, proxying the API to :8000). Neither is required — the API
starts without it, and `/live` is a no-build fallback page for watching a stream.

## Tests

```bash
uv run ruff check .          # lint
uv run mypy                  # strict, src/ only
uv run alembic upgrade head  # migrations apply
uv run pytest                # 454 tests
```

The same four steps CI runs, in the same order — cheapest first, so a typo is caught in a
second rather than after a database is up.

Two guards make the suite safe to run anywhere, both in `tests/conftest.py`:

| Guard | What it prevents |
|---|---|
| The DSN must end in `_test` | Every Postgres fixture drops its schemas on teardown. `conftest` rewrites `DATABASE_URL` to a sibling database ending `_test` and creates it; `test_postgres.py` asserts it again. A stray DSN can never wipe a real database. |
| `ALLOW_MODEL_REQUESTS = False` | Any real provider call raises instead of going to the network. A test suite that can spend money is one nobody runs. |

87 of the tests need a reachable Postgres (`test_postgres.py`, `test_auth.py`); without one
they skip rather than fail. The rest run straight after `uv sync`. SQLite is never used —
it has no schemas, no `ON CONFLICT ... ON CONSTRAINT`, no JSONB and no advisory locks,
which is most of what can break here.

To get a database for them:

```bash
docker run -d --name mycel-test-pg -p 5433:5432 \
  -e POSTGRES_USER=pg -e POSTGRES_PASSWORD=pg -e POSTGRES_DB=mycel \
  postgres:16-alpine

DATABASE_URL=postgresql://pg:pg@localhost:5433/mycel uv run pytest
```

The frontend is checked separately, because it needs Node and no database:

```bash
cd web && npm ci && npx tsc --noEmit && npm run build
```

**Evals are not tests.** Tests catch broken code; evals catch a report that has no error and
is simply worse than last time. They call the real model, so CI runs them only when a PR
touches `src/mycel/agents/`, `src/mycel/llm/` or `evals/` — see [evals/](evals/README.md).

## Directory tree

```
src/mycel/     Source — see docs/ for what each layer does
web/           The UI: React + TypeScript, built into the image, served at /app
config/        Per-environment, per-agent and per-source YAML (secrets live in .env)
deploy/        Infrastructure config: OTel, Grafana, vLLM, deploy environments
evals/         Golden set for scoring report quality
migrations/    Alembic migrations
docs/          Design documentation
tests/         Tests
```

## Documentation

| | |
|---|---|
| **[docs/using-mycel.html](docs/using-mycel.html)** | How to use it: sign up, connect Jira, read the report |
| [notes/flow/reference/testing.html](notes/flow/reference/testing.html) | 🇻🇳 How to run the tests, and what each one proves |
| **[docs/architecture.html](docs/architecture.html)** | How the system is put together — read this first |
| **[docs/database.html](docs/database.html)** | Schemas, tables and every column, with diagrams |
| [deploy/inference/](deploy/inference/README.md) | Hardware constraints for the local model |
| [deploy/envs/](deploy/envs/README.md) | Environment variables and how to reach staging/prod |
| [evals/](evals/README.md) | Re-run before merging any prompt or model change |
