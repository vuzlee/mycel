# Mycel

A multi-agent system that automatically assembles **reports and dashboards** from scattered
data sources — Slack, Gmail, Confluence.

Named after *mycelium*, the underground fungal network that connects a whole forest. Mycel
works the same way: running in the background, quietly gathering data, processing it through
several layers, and only then surfacing as a report.

> **Status:** scaffolding. No connector runs for real yet.

## What it does

```
Slack · Gmail · … ──► raw ──► silver ──► gold ──► Agents ──► Reports / Dashboards
                      raw     cleaned   ready
```

All three layers live in one **PostgreSQL**, one schema each. Agents read `gold` only.

Reasoning goes through `llm/` — high-volume work runs on a local model, final reasoning calls
a cloud model. No module imports a provider SDK directly.

## Running it

```bash
cp .env.example .env      # fill in DB and API keys
docker compose up -d      # app + postgres + observability
```

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

Without Docker: `uv sync`, then `uvicorn mycel.api.app:app --reload`.
To enable the local model (needs a GPU): add `--profile local-llm`.

## Directory tree

```
src/mycel/     Source — see docs/ for what each layer does
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
| **[docs/architecture.html](docs/architecture.html)** | The full version with diagrams — read this first |
| [docs/architecture.md](docs/architecture.md) | Same content, plain text |
| [deploy/inference/](deploy/inference/README.md) | Hardware constraints for the local model |
| [deploy/envs/](deploy/envs/README.md) | Environment variables and how to reach staging/prod |
| [evals/](evals/README.md) | Re-run before merging any prompt or model change |
