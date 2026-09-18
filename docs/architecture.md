# Mycel architecture

> Visual version with layered diagrams: [architecture.html](architecture.html)
> · Tech stack tracking table: [stack.html](stack.html)

## Principles

1. **One direction.** Data only flows raw → silver → gold. No layer reads back upwards.
2. **Agents read gold only.** Agents never touch raw/silver — gold is the only contract.
3. **Adding a source does not change existing code.** A new provider = one file in `sources/`.
4. **Models are called only through `llm/`.** No module imports a provider SDK directly.
5. **Slow work goes on the queue.** The API does not wait for an LLM to finish.
6. **Changing a prompt means running the evals.** A worse report does not turn a test red.
7. **Thin controllers, thick pipelines.** If `api/` could be deleted entirely and `scheduler` would still produce reports, the layers are in the right place.
8. **One image for every environment.** Built once, tagged by commit SHA. Only environment variables differ.
9. **Module name = what it does.** No abbreviations, no surplus abstraction layers.

## The three data layers

| Layer | Schema | Holds | Written by |
|---|---|---|---|
| **raw** | `raw` | The provider's original payload, untouched. Kept so it can be replayed. | `sources/` |
| **silver** | `silver` | Schema normalised, deduplicated, types coerced, timestamps unified. | `etl/` |
| **gold** | `gold` | Tables aggregated for the business, ready for queries and reports. | `etl/` |

Keeping raw untouched matters most: when transform logic turns out to be wrong, it can be
re-run from raw instead of calling the provider again.

## The modules

### `core/`
Config read from env/file, logger, base exceptions, shared types. Imports no other module in
`mycel` — this is the bottom layer.

`agents/core/` follows the same shape, one level narrower: the shared foundation for `agents/`
only.

### `storage/`
Three stores, three different kinds of data. Every access goes through here.

| | Backend | Holds |
|---|---|---|
| `postgres/` | PostgreSQL 16 | Transactional state: the raw/silver/gold layers, jobs, permissions |
| `vectors/` | Qdrant | Embeddings for knowledge base search |
| `objects/` | MinIO (S3 API) | Large files: source PDFs, rendered reports |

Why not put everything in Postgres:

- **Vectors.** `pgvector` works, but at a few million vectors the HNSW index competes for RAM
  with the transactional workload on the same instance. Split out, they scale independently.
- **Files.** Blobs in Postgres bloat the database, slow backups down, and every read pulls the
  whole file through a pooled connection. The API returns a presigned URL; a 200MB file never
  passes through the API process.

Postgres holds file **metadata** (which report it belongs to, the bucket key); the bucket holds
the **content**. Never the other way round.

Embeddings are built from **gold**, not raw — the same contract the agents read, so search
results and table query results cannot contradict each other. View permissions are pushed down
into the Qdrant filter, not applied after top-k: fetching 10 results and then dropping the
ones the user may not see can leave 2.

Every SQL statement, every vector query, every file operation lives here rather than being
scattered through pipelines and agents. Using the S3 API means moving to real S3 later is just
an endpoint change.

### `sources/`
One module per provider: `sources/slack.py`, `sources/gmail.py`, … All with the same interface:
take the time range to sync, return raw records, write them to `raw`. No processing, no
cleaning — that is the pipeline's job.

Per-source configuration (endpoint, scopes, rate limits) lives in `config/sources/`.

### `etl/`
The data transformation steps: raw → silver → gold. This is scheduled background ETL, **not**
the request-handling chain — that lives in `managers/<domain>/pipeline.py`.

Each step is a pure function: read from the layer below, write to the layer above, idempotent —
running it twice gives the same result.

`etl/checks/` validates after every step: missing columns, unexpected nulls, row counts off by
more than a threshold. On failure it stops and does not write to the layer above. Providers
change their schema without warning all the time; without the checks, gold breaks silently and
the agents confidently report wrong numbers.

### `llm/`
The only gateway to any model. No module imports a provider SDK directly — which is why
switching models, adding a cache or setting a spend ceiling is a change in one place.

| File | Does |
|---|---|
| `router.py` | Picks local or cloud for each call |
| `client.py` | The only place that imports a provider SDK — calls the real model, returns a result or a stream of deltas |
| `providers/` | Per-provider differences: `local.py` (vLLM), `cloud.py` |
| `cache.py` | Repeated prompt returns the previous result instead of calling again |
| `tokens.py` | Counts tokens *before* sending, so the block happens up front rather than after paying |
| `usage.py` | Counts *after* the call: tokens, cache hits, duration. Counted once, used in three places — budget, trace, log |
| `budget.py` | Accumulates tokens per job; over the ceiling it raises instead of calling again |

The local/cloud boundary:

- **local** — high-volume work, short output, or sensitive data that should not leave the
  machine: classification, entity extraction, relevance scoring, per-record summaries.
- **cloud** — the final reasoning: synthesising several sources, writing the report, decisions
  that need long context.

A 3B model is not good enough to write a report, so it carries the volume, not the conclusions.
Specific hardware constraints: `deploy/inference/README.md`.

### `agents/`
Split into two layers, because they change at different rates: how a run is wired barely
changes, while prompts change constantly.

**Built on pydantic-ai.** The run loop, message types, streaming and usage accounting are the
framework's. What is left below is only the part specific to Mycel — which is why there is no
`agent.py`, no `schemas.py` and no `streaming/`: `Agent`, `ModelMessage` and
`run_stream_events()` replace them outright.

**The framework — `agents/core/`**, the shared foundation for `agents/` only, with no business
logic. Same shape as `mycel/core/` but one level narrower: a `core/` nested inside a package
always means "the shared foundation of that package".

| | Does |
|---|---|
| `runner.py` | The one place a top-level run starts, and so the one place the budget is charged. `delegate` runs on the caller's usage and deliberately charges nothing |
| `config.py` · `model_builder.py` | Models declared as `'<tier>:<model_name>'`; the builder turns a spec into a client with timeouts and retries attached |
| `deps.py` | What one run carries: `job_id`, budget, settings. Named `deps`, not `run_context` — pydantic-ai owns that name and means something else by it |
| `guards.py` | Degenerate-loop detection only. Runaway limits and schema retries are `UsageLimits` and `ModelRetry`, i.e. configuration rather than code |
| `exceptions.py` | Where pydantic-ai's failures become Mycel's, named with the tier that produced them |

**The business layer** on top:

- **`agent/`** — `analyst.py` · `researcher.py` · `librarian.py`, one job each: figures from
  gold, facts from the web, passages from the knowledge base. All three share a shape — take a
  question, return statements with their sources — so the orchestrator composes them without
  knowing how they differ. A single job means a short prompt, evals that can score each one, and
  a clear culprit when something breaks. Each file is a prompt and an output schema; the tools it
  uses come from `tools/`.
- **`tools/`** — each module owns a capability end to end and exports a `build_toolset()`. An
  agent lists the toolsets it wants and writes no wrappers, so the second agent to need a tool
  adds a line rather than copying code.
- **`orchestrator.py`** — takes a report request, splits it into tasks, hands them out, merges
  the results. It does no analysis and writes no prose itself. Outside `agent/` because it
  coordinates specialists rather than being one. Not named `manager.py`, to avoid confusion with
  `managers/` — that is the per-domain HTTP entry point.
- **`registry.py`** — declares the agents and tools the orchestrator may use. Adding an agent =
  adding a line.

**Not built yet: streaming beyond a single agent.** `run_stream_events()` covers one run, but
routing several agents' events into one stream a client can untangle needs an envelope carrying
which agent an event came from and which tool call it sits under — and jobs run in a separate
worker process, so an in-process queue does not reach the HTTP layer. See `api/__init__.py`.
Agents return structured, validated output; if the model returns the wrong format it retries
rather than letting broken data travel further.

**Two error conventions in `tools/`, and picking the wrong one is expensive.** `compute.py`
raises `ModelRetry` because its failures are argument failures — the model fixes them by calling
again with different numbers. A tool that does I/O cannot: when a quota runs out or Qdrant is
down, re-prompting sends the model round the same loop until `max_retries` turns it into a run
error. Those raise `ToolFailed`.

**Guards are not budgets.** The budget counts money across the whole job; a guard counts the
behaviour of a single run. A broken loop hits a guard within seconds; by the time it hits the
budget the money is already spent.

### `queue/`
The job layer sits **on top of** Kafka; it is **not** the broker — Kafka runs outside, declared
in `docker-compose` (KRaft mode, no Zookeeper). Changing broker is a change here, and the rest
of the system never notices.

`scheduler/` answers *when to run*; `queue/` answers *what to run and what happens on failure*.
Producing a report takes minutes and will sometimes fail halfway, so:

- The API pushes the work onto the queue and returns a `job_id` immediately; the client does not wait.
- Every job has an idempotency key — a re-run does not produce two duplicate reports.
- Failures retry; out of retries they go to a dead-letter topic to be inspected, not lost quietly.

| File | Does |
|---|---|
| `job.py` | The shape of a job: payload, idempotency key, retry count, trace context |
| `producer.py` | Pushes a job to the topic: partition chosen by key, `acks=all`, trace context injected |
| `consumer.py` | Pulls jobs and runs them, commits once done |
| `retry.py` | Tiered retry topics and dead-letter |
| `context.py` | Carries trace context across the process boundary — see `observability/` |

**Four things Kafka does not give you, which have to be built.** Kafka is an ordered log, not a
task queue, so:

| | Why | How |
|---|---|---|
| No per-job retry | Kafka commits by offset; a `seek` backwards blocks the whole partition | Push to a retry topic and commit onward: `jobs` → `jobs.retry.1m` → `jobs.retry.10m` → `jobs.dlq` |
| Kafka does not count retries | There is no concept of an "attempt" | Count it in the message header |
| No delayed messages | Kafka does not delay | The retry topic's consumer sleeps until the message is old enough |
| Long jobs look dead | `max.poll.interval.ms` defaults to 5 minutes; a report takes minutes | Raise it (`KAFKA_MAX_POLL_INTERVAL_MS`); exceed it and there is a rebalance and the job restarts from the beginning |

**Partition count is the parallelism ceiling, not the worker count.** With a 6-partition topic
the 7th worker sits idle — even if the HPA has started enough pods. Partitions can be increased
but not decreased, and increasing them breaks per-key ordering.

**Commit after finishing, not on receipt.** A worker that dies mid-job has the job handed to
someone else — which is what we want, but it makes delivery at-least-once, so the idempotency
key in `job.py` is **mandatory**, not optional. That key must be derived from the content of the
work (domain + time range + parameters), not a freshly generated UUID.

In exchange Kafka gives two things most brokers do not: a replayable log, and the ability to add
a new consumer group that re-reads the same stream without affecting the group already running.

Trace context lives in the message **header**, not the payload, so it follows the job into the
retry and dead-letter topics too — a job in the DLQ can still be traced back to the moment the
button was pressed.

### `reports/`
Turns agent output into the final artifacts: text reports, data tables, dashboards.

### `managers/`
The system's entry points, **split by business domain**. HTTP does not call services directly —
it calls into the manager for the matching domain:

```
managers/report/          everything to do with reports
  controller.py           HTTP endpoints — receive, validate, call the pipeline, return
  pipeline.py             the business chain — calls services in order
  schemas.py              the shape of data in and out over HTTP
managers/sync/            the source-sync domain, the same three files
```

Adding a domain = one directory here + one `include_router` line in `api/app.py`. Existing
domains are untouched.

Why split by domain rather than by technical role: changing one piece of business logic means
opening exactly one directory instead of jumping between `routes/`, `services/` and `pipeline/`
in three different places.

**The pipeline is the chain, services are the links.** `managers/report/pipeline.py` defines the
*order*: `permission` → `enqueue` → *(a worker picks the job up)* → `gather` → `analyze` →
`render`. `managers/sync/pipeline.py`: `fetch` → `transform` → `check`. The pipeline does no
work itself; it only wires services together.

### `services/`
One file = one single job, done end to end: `permission.py`, `enqueue.py`, `fetch.py`,
`transform.py`, `gather.py`, `analyze.py`, `render.py`, `check.py`.

File names are verbs with no `_service` suffix — they are already in `services/`.

Services must be reusable — `gather.py` serves both the report domain and the sync domain. It
does not know which chain it is in, and does not know who called it: HTTP and the scheduler look
the same to it.

Complex business logic (transforms, reasoning, artifact building) lives in `etl/`, `agents/` and
`reports/` — services only call into it.

### `scheduler/`
Answers *when to run*: hourly source syncs, transforms after a sync finishes, daily/weekly
reports. It calls `pipeline` in `managers/` directly — the same place controllers call, just
without the HTTP link in the chain. It never makes HTTP calls into itself.

### `api/`
The HTTP shell, as thin as possible. Business endpoints are **not** here — they are in
`managers/<domain>/controller.py`.

| File | Does |
|---|---|
| `app.py` | The assembly point: create the app, mount each manager's controller, middleware, observability. `uvicorn mycel.api.app:app` points here |
| `middleware.py` | Only `request_id` — everything else uses what already exists |
| `dependencies.py` | What controllers declare via `Depends()`: authentication, DB session, pagination |
| `health.py` | `/health/live` for container restart policy, `/health/ready` for the load balancer (DB reachable, migrations applied). Belongs to no business domain |

`app.py` is the only file that knows which domains the system has.

**Only one middleware is written by hand.** Most of what tends to get hand-written already
exists, and writing it yourself means maintaining a re-implementation of something standardised:

| Job | Use |
|---|---|
| A span per request | `FastAPIInstrumentor.instrument_app(app)` — correct OTel semantic conventions |
| CORS | Starlette's `CORSMiddleware` |
| One error shape | `@app.exception_handler(...)` — FastAPI's own mechanism, not middleware |
| Rate limiting | Nginx/ingress blocks before it reaches the app; per-user needs `slowapi` |
| Authentication | `Depends()` — see below |
| **`request_id`** | **Hand-written** |

`request_id` is hand-written because the valuable part is putting the id into `contextvars`
(a Python built-in, not a FastAPI feature) so `observability/logging.py` picks it up on its own —
controllers never have to write `log.info(..., request_id=rid)` on every line. The logger is
ours, so no library can do that part for us.

**Write it as pure ASGI, not `BaseHTTPMiddleware`.** That one buffers the response and therefore
blocks SSE — and `agents/core/streaming/` exists precisely to stream. The failure is silent: the
tokens simply all arrive in one lump at the end.

**Authentication is `Depends()`, not middleware.** Three concrete reasons: middleware runs for
every route, so it has to maintain its own exclusion list for `/health` and `/docs`; a dependency
reaches the OpenAPI schema, so `/docs` shows the padlock; and a controller receiving
`user: User = Depends(current_user)` is typed and checkable under mypy strict — middleware only
stuffs things into `request.state`, where mypy sees nothing.

There is authentication — the data inside is internal Slack and Gmail. It only answers *who you
are*; *which reports you may see* is `services/permission.py`'s job, because that needs business
context the HTTP layer does not have.

### One request through the layers

| Layer | Who | May do |
|---|---|---|
| Shell | `api/app.py` | Create the app, mount controllers, middleware, observability. No endpoints, no business logic |
| Entry | `managers/*/controller.py` | Receive · validate · call the pipeline · return |
| Chain | `managers/*/pipeline.py` | Define the order of the steps. The only layer both `api/` and `scheduler/` call |
| Link | `services/` | One single job, reusable across pipelines |
| Domain | `etl/` `agents/` `reports/` | The real business rules |
| Data | `storage/` | Every SQL statement |

Quick sanity check: if `api/` were deleted entirely and `scheduler` could still produce reports,
the layers are in the right place.

**Two axes, do not confuse them.** The data axis `sources → raw → etl → silver → gold` runs in
the background on a schedule, measured in minutes. The request axis
`controller → pipeline → service` runs when someone presses a button, measured in seconds. They
meet in exactly one place: at `gold`.

### `observability/`
The only module that cuts across every layer, so it has to stay very thin and hold no business
logic.

| File | Does |
|---|---|
| `tracing.py` | Sets OTel up once at startup, exports OTLP. Only handles the transport-independent part — HTTP spans are `FastAPIInstrumentor`'s job. Can be switched off by env |
| `llm_trace.py` | LLM-specific span attributes, following the convention Langfuse reads: model, input, output, tokens, cost |
| `logging.py` | JSON logs, every line carrying `trace_id` · `request_id` · `job_id`. Printed to stdout, collected into Loki by Promtail |
| `metrics.py` | Sync latency, record counts per layer, tokens spent, job failure rate |

**Three signals, three different questions** — all three are needed and none substitutes for
another:

| | Backend | Answers |
|---|---|---|
| Metrics | Prometheus | *Is something broken* — latency spiking, job failure rate climbing |
| Traces | Tempo | *Where* — which model call is slow, which of the five services |
| Logs | Loki | *Why* — the stack trace, the payload the provider returned |

They join up because `trace_id` appears in all three: from a spiking metric, click through to the
slowest trace; from a span, click through to exactly that trace's log lines. Grafana provisions
both directions in `deploy/grafana/datasources/`.

`trace_id` lives in the **body** of the JSON log line, not as a Loki label — Loki creates one
stream per distinct label value, and `trace_id` is almost never repeated. Grafana picks it up
with a derived field.

The app only **prints logs to stdout** and sends them nowhere itself: Promtail collects the
container's stdout and ships it to Loki, and in K8s the mechanism is the same. That way no module
knows Loki exists.

Nothing here knows what HTTP is — the HTTP-specific part lives in `api/`, and `api/app.py` calls
`tracing.setup()` and leaves request spans to `FastAPIInstrumentor`. That lets `scheduler`,
`queue` and `etl` import this module without dragging in the web layer.

**Three ids from three different sources** — commonly confused:

| | Generated by | Used for |
|---|---|---|
| `trace_id` | OTel itself, once instrumented. Read from the current span | Joining logs ↔ traces |
| `request_id` | Us, in `api/middleware.py` | Returned to the client — the id a bug report quotes |
| `job_id` | Us, when pushing to `queue/` | Joining a request to the background work that follows |

The logger does **not** know `trace_id` by itself: every log call reads the current span and
attaches it. That is the one join that has to be written by hand, and also what makes jumping
from a log line straight to its trace possible.

One report request is a tree of spans: HTTP → pipeline → queue → worker → orchestrator → each
agent → each model call. A report with wrong numbers, or a slow one, can be traced back to the
exact call responsible.

**The queue is where traces break most easily.** The worker is a different process and
`contextvars` do not cross a process boundary, so trace context does **not** follow the job on
its own. Do nothing and Grafana shows two unrelated traces — an HTTP one ending at the word
"accepted", and a report one appearing out of nowhere. Nothing reports an error.

The join: `queue/context.py` injects trace context into the message **header** on enqueue and
extracts it when the worker receives it, using OTel's W3C `traceparent` — the same standard as
the HTTP header. It has to be done by hand at both ends; forget one and nothing errors, there are
just two separate trace trees.

The call into `llm_trace.py` is in `agents/core/hooks.py`; the rest of the system never needs to
know the attribute names.

Metrics answer *is something broken*, traces answer *where*. Both are needed.

## Dependency order

```
core ◄── storage ◄── sources
             ▲   ◄── etl
             │
             └──────► agents ◄── llm
                        ▲  ▲
                 reports┘  └ services ◄── managers ◄── api, scheduler
                                            ▲
                                         queue
```

Arrows mean "is imported by". `core` depends on nothing; `api` and `scheduler` sit at the top and
both go through `managers`. `observability` is a deliberate exception: every layer imports it.

## Operations

`docker compose up` brings up six containers — the minimum a job needs to run end to end.
Everything else sits behind a profile, so a single dev box is not asked to hold a stack it has
no data for.

| Service | Role | In the default `up` |
|---|---|---|
| `postgres` | One database, three schemas. Separate volume so upgrading the image does not lose data | yes |
| `rabbitmq` | The job queue: one consumer per message, redelivery on crash, a dead-letter exchange for retries | yes |
| `redis` | Agent events on their way to the browser, one Stream key per run, expired by TTL | yes |
| `qdrant` | Vector store — knowledge base search | yes |
| `worker` | Pulls jobs and runs them. `--scale worker=N` with no partition ceiling | yes |
| `scheduler` | Background runner — syncs, transforms, periodic reports | yes |
| `api` | The front door — accepts report requests, health checks | `--profile api`; in dev it runs on the host under `uvicorn --reload` |
| `vllm` | Optional local model | `--profile local-llm` |
| `prometheus` · `loki` · `promtail` · `grafana` | Metrics over time and logs across machines | `--profile monitoring` |

**Traces are not in that stack at all.** The app exports OTLP straight to Langfuse Cloud, which
is the view that actually gets read: an agent run as a tree of calls with their prompts, tokens
and cost. Tempo held the same spans but rendered them as a generic trace, and the collector in
front of it only forwarded them, so both are gone. Prometheus, Loki and Grafana answer questions — how has latency moved this week, what did the other three machines log
— that a single dev box has no data for. They stay declared so turning them on is one flag.

Object storage is not here at all: a report is markdown, which is a `TEXT` column.

## From dev machine to cluster

The whole system runs **on-premise**, with no dependency on a cloud service beyond the final LLM
call.

| | Runs on | Used for |
|---|---|---|
| `docker-compose.yml` | a developer's machine | writing code, debugging, trying things out |
| `deploy/helm/` | the on-prem Kubernetes cluster | staging, prod |

Two different files, but the **same image** and the same set of environment variables. There is
no `if env == "prod"` branch in the code.

```
git push ──► CI (lint · types · migrations · test) ──► build image (tag = SHA)
                  └─ evals only run when prompts/ or llm/ are touched   │
                                                                        ▼
                                                        Harbor (internal registry)
                                                                        │
                          CI edits image.tag in values ◄────────────────┘
                                      │
                          Argo CD sees git change ──► helm upgrade ──► K8s cluster
                                                        ├──► staging (auto-sync)
                                                        └──► prod   (a human clicks)
```

CI has **no** access to the cluster — it only builds the image and edits one line in git. Cluster
credentials live in Argo CD.

### Why Kubernetes rather than compose on a real host

Four things compose cannot do:

| Requirement | How K8s does it |
|---|---|
| The API can scale | `Deployment.replicas` — many pods behind one Service |
| A dead pod comes back | kubelet restarts the container; the Deployment recreates a lost pod |
| More traffic adds pods | `HorizontalPodAutoscaler` |
| Services can reach each other | `Service` — one stable DNS name, load-balanced already |

`docker compose up -d` can restart a dead container, but it cannot move the work to another
machine when the **machine** dies, and it does not scale with load.

**Self-healing only works when the probes are right.** A hung pod that still has its port open
looks healthy to K8s: no restart, and the Service keeps sending requests. `readinessProbe`
decides whether it takes requests, `livenessProbe` decides whether it restarts, `startupProbe`
delays the other two during boot — without the last one `vllm` gets killed unfairly, because
loading the model takes minutes.

**HPA: a different measure per service.** `api` on CPU. `worker` on **Kafka consumer lag**,
because workers mostly wait on I/O so CPU stays low while the queue backs up — this needs KEDA or
prometheus-adapter. `vllm` does **not** autoscale: each pod holds a GPU, and with no free GPU a
new pod only sits Pending.

**`worker`'s hard ceiling:** actual running pods = min(replicas, partition count). So set
`maxReplicas` to the partition count, not higher.

**Stateful services run as `StatefulSet` + PVC**, not `Deployment`: Postgres, Kafka, Qdrant and
MinIO need a stable identity and a volume that reattaches to the same pod. On-prem means
providing the storage layer yourself (k3s local-path, or Longhorn if volumes should be able to
move between machines) — the most labour-intensive part of leaving the cloud. Details:
`deploy/kubernetes/README.md`.

### Helm — reproducible deploys

Hand-written YAML means one copy per environment, edits applied in one place and forgotten in
two others, and nobody able to answer "what configuration is prod running". Helm packs it into a
versioned chart: the same chart + `values-prod.yaml` always produces the same result.

Do not mix the two versions: `version` is the chart's (template edits), `appVersion` is the
image's commit SHA (a new build). Rolling back the chart does not roll back the code.

`scheduler` is always `replicas: 1` with `strategy: Recreate` — two schedulers fire every
schedule twice, and `RollingUpdate` starts the new pod before removing the old one, leaving a
window with two alive.

Migrations still run first, declared as a `pre-upgrade` hook running `alembic upgrade head`. If
the hook fails Helm stops and the new pods never start. Secrets are not in values — the chart
only references `Secret` names. Details: `deploy/helm/README.md`.

### Argo CD — GitOps

Deploying by hand leaves nobody able to answer *what is prod running* and *who changed it when*.
Argo flips the direction: git is the source of truth, Argo compares the cluster against git and
pulls it into line.

Two things to be careful with: `prune` deletes resources no longer in git — set it `false` for
anything with state, because one wrong line in values pruning Postgres's PVC is an accident git
cannot fix. And `selfHeal` overwrites every `kubectl edit` — convenient normally, but it removes
the hot-patch route during an incident. So **staging auto-syncs, prod needs a human**. Details:
`deploy/argocd/README.md`.

### Harbor — internal registry

An on-prem cluster needs its images in-house: no Docker Hub rate limits, and images containing
internal code do not go to a public registry. Beyond storing images, Harbor adds CVE scanning
(Trivy), image signing (Cosign), RBAC + audit log, and tag retention policies — one tag per
commit fills a disk within months without cleanup.

The most practical reason is the **proxy cache**: every third-party image (postgres, kafka,
qdrant, minio, grafana, …) goes through Harbor, so the cluster can be rebuilt even with no
outbound network.

Tag = commit SHA, never `latest`: `latest` lets two pods with the same manifest run different
code, and leaves rollback with no version to go back to. Details: `deploy/registry/README.md`.

Environment variable and secret details: `deploy/envs/README.md`.

## Deferred designs

Specs for files removed before they were written. Each was a docstring in the tree; keeping
the design here and the tree small is cheaper than carrying an empty module that reads as
half-built work.

### Agents

**`agent/writer.py`** — writes the prose of a report from the analyst's results. May only use
numbers already present in its input; if it needs more it returns a request rather than
deriving them itself. Waits on the analyst's output schema settling.

**`agent/reviewer.py`** — checks a draft against the source data: do the numbers match, which
sentences cannot be traced back to a source. Runs after the writer, before `reports/` builds
the final artifact. Only meaningful once a writer exists.

### Tools

**`tools/query_gold.py`** — queries the gold layer through `storage/` rather than writing SQL
itself, and reads gold only; agents never touch raw or silver. A cap on rows returned, because
one table-scanning question would blow up the context and burn money for nothing. Waits on
`storage/`.

**`tools/search_docs.py`** — semantic search over the knowledge base via `storage/vectors/`.
Returns passages together with their **source** (which gold record, original link), not content
alone: without a source a reviewer has no way to verify anything and the report becomes a set
of assertions that cannot be cited. View permissions are pushed down into Qdrant's filter, not
applied after results come back. Folded into `rag_search.py`, which carries the same two rules.

**`tools/chart.py`** — builds a chart from a dataset and returns a chart *spec* for `reports/`
to render, not an image. Waits on a report renderer.

Two lookup routes for two kinds of question: `query_gold` answers anything needing exact
figures ("Q3 revenue"), semantic search answers vague ones ("who discussed this"). Get it the
wrong way round and the agent hunts for a number via semantic search and invents something
approximately right.

### Integrations

**`core/integrations/mcp.py`** — moved out of the agent layer to `mcp/clients.py`: MCP is a
boundary of the system, not an internal detail of how an agent runs. External tools are someone
else's code, so they need a timeout and a cap on result size, and their descriptions travel
straight into the prompt — which is why servers are declared in config and never discovered.

**`core/integrations/agent_protocol.py`** — talking to another system's agent over an
agent-to-agent protocol. Deferred until there is a second system to call.

## Growing later

When a module outgrows a file it becomes a directory with the same name:
`sources/slack.py` → `sources/slack/{client.py,parser.py}`. There is no need to pre-build a
`domain/application/infrastructure` layering with nothing to put in it yet.

## Report quality

Tests catch code bugs. A worse report does not turn a test red — the output is still correctly
formatted, just worse. That is `evals/`'s job: a golden set of *gold data → report a human finds
acceptable* pairs. Changing a prompt, changing a model or bumping an agent version all mean
re-running it and comparing against the previous score. A drop blocks the merge.
