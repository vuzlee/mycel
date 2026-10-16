<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/banner-dark.svg">
  <img src="assets/banner-light.svg" alt="Mycel — ask your issue tracker a question in plain language" width="100%">
</picture>

<p>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-6d3fd1?style=flat-square&labelColor=2b2536">
  <a href="https://github.com/vuzlee/mycel/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/vuzlee/mycel/ci.yml?branch=main&style=flat-square&label=ci&labelColor=2b2536&color=6d3fd1"></a>
  <img alt="Ruff" src="https://img.shields.io/badge/lint-ruff-6d3fd1?style=flat-square&labelColor=2b2536">
  <img alt="mypy strict" src="https://img.shields.io/badge/mypy-strict-6d3fd1?style=flat-square&labelColor=2b2536">
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-6d3fd1?style=flat-square&labelColor=2b2536"></a>
</p>

</div>

Ask your work a question in plain language. Mycel reads Jira, Gmail, Calendar and your
documents, answers with the sources it used, and books or updates things only after you say yes.

https://github.com/user-attachments/assets/c8546f73-e6a8-4aca-abb1-08c07a849eb0

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/flow-dark.svg">
  <img src="assets/flow-light.svg" alt="High-level design: users, Jira, Gmail, Calendar and MCP servers outside; scheduler, connectors, ETL and ingest feed Postgres, Redis, Qdrant and MinIO; the API puts a question on RabbitMQ, a worker runs agents that call models through LiteLLM (cloud or vLLM), and search the web through Tavily; Langfuse traces every agent run; Prometheus, Loki and Grafana watch every service" width="100%">
</picture>

## Features

- **Ask in plain language** — progress, what is late, who logged what, with charts when numbers help.
- **Knowledge** — upload PDF, Word or Markdown; answers quote the passage and link the page.
- **Mail and calendar** — triage your inbox, book a meeting after you confirm the draft.
- **Your model** — host models through LiteLLM, or your own OpenAI-compatible keys.
- **Self-hosted** — one team, your database, your keys. Not built to face the internet.

## Quickstart

```bash
cp .env.example .env
scripts/stack.sh doctor   # what is missing, and what each absence costs
scripts/stack.sh dev up   # stores, migrations, API, workers, scheduler
```

Open <http://localhost:8000/app> and sign in with Google or an emailed code.
First-time setup — the Jira service account and the OAuth apps — is in
[docs/setup.md](docs/setup.md).

## Development

```bash
uv run ruff check . && uv run mypy && uv run pytest   # backend
cd web && npm run lint && npm test && npm run build   # frontend
```

Answer quality is scored separately, see [evals](evals/README.md).
Design notes: [architecture](docs/architecture.html) · [database](docs/database.html).

## License

[MIT](LICENSE) © 2026 vuzle
