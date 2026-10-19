"""Which handbook page owns which source file: every file has exactly one owner page.

    python docs/tools/coverage.py      # files with no page or two pages; pages that do not exist

Paths are repo-relative; a trailing "/" owns everything under it. An empty list is a page
that explains across files (a how-to, a map) and owns none.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

#: Where source lives, and the suffixes counted as source.
SCANNED = {
    "src/mycel": (".py",),
    "web/src": (".ts", ".tsx", ".css"),
    "config": (".yaml", ".yml", ".py", ".sh"),
    "migrations": (".py",),
    "scripts": (".sh", ".mjs", ".md"),
    "deploy": (".yaml", ".yml", ".tpl", ".md", ".alloy"),
    "evals": (".py", ".yaml", ".json"),
}

#: Pages that own no file by design.
KEPT = {
    "index.html",
    "glossary.html",
    "decisions.html",
    # The old single walkthrough; split into flows/* as those pages are written, then removed.
    "flows/using-mycel.html",
}

PAGES: dict[str, list[str]] = {
    "overview/architecture": [],
    "overview/code-map": [],
    "overview/config": [
        "src/mycel/core/config.py",
        "src/mycel/core/config_files.py",
        "src/mycel/core/settings_source.py",
        "config/environments/",
        "config/agents/",
        ".env.example",
    ],
    "overview/core-types": [
        "src/mycel/core/principal.py",
        "src/mycel/core/usage.py",
        "src/mycel/core/exceptions.py",
        "src/mycel/core/chips.py",
        "src/mycel/core/__init__.py",
    ],
    "overview/database": [
        "src/mycel/infra/postgres/models/app.py",
        "src/mycel/infra/postgres/models/documents.py",
        "src/mycel/infra/postgres/repositories/identity.py",
        "src/mycel/infra/postgres/repositories/accounts.py",
        "src/mycel/infra/postgres/repositories/documents.py",
        "src/mycel/infra/postgres/repositories/models.py",
        "src/mycel/infra/postgres/repositories/own_models.py",
        "src/mycel/infra/postgres/repositories/conversations.py",
    ],
    "overview/processes": [
        "src/mycel/lifecycle.py",
        "src/mycel/worker.py",
        "src/mycel/scheduler/__main__.py",
        "src/mycel/__init__.py",
    ],
    "flows/ask-a-question": [
        "src/mycel/api/routes/chat.py",
        "src/mycel/services/chat.py",
        "src/mycel/domains/chat.py",
        "src/mycel/domains/chat_model.py",
        "src/mycel/infra/redis/results.py",
        "src/mycel/api/routes/conversations.py",
        "src/mycel/services/conversations.py",
        "src/mycel/domains/__init__.py",
    ],
    "flows/connect-accounts": [
        "src/mycel/api/routes/connections.py",
        "src/mycel/services/oauth.py",
        "src/mycel/services/google_oauth.py",
        "src/mycel/services/jira_oauth.py",
        "src/mycel/services/access_tokens.py",
        "src/mycel/infra/redis/access_tokens.py",
        "src/mycel/services/tokens.py",
    ],
    "flows/own-model": [
        "src/mycel/api/routes/models.py",
        "src/mycel/services/models.py",
        "src/mycel/services/own_models.py",
    ],
    "flows/sign-in": [
        "src/mycel/api/routes/auth.py",
        "src/mycel/services/auth.py",
        "src/mycel/services/google_signin.py",
        "src/mycel/services/signin_code.py",
        "src/mycel/devtools/",
    ],
    "flows/upload-document": [
        "src/mycel/api/routes/documents.py",
        "src/mycel/services/documents.py",
    ],
    "queue/consumer": [
        "src/mycel/queue/consumer.py",
        "src/mycel/queue/handler.py",
        "src/mycel/queue/context.py",
        "src/mycel/queue/__init__.py",
    ],
    "queue/idempotency": [
        "src/mycel/infra/redis/claims.py",
        "src/mycel/infra/redis/deliveries.py",
    ],
    "queue/outbox": [
        "src/mycel/services/enqueue.py",
        "src/mycel/infra/postgres/repositories/outbox.py",
    ],
    "queue/producer-topology": [
        "src/mycel/queue/producer.py",
        "src/mycel/queue/topology.py",
        "src/mycel/queue/connection.py",
        "src/mycel/queue/job.py",
    ],
    "queue/retry-dlq-replay": [
        "src/mycel/queue/retry.py",
        "src/mycel/queue/replay.py",
    ],
    "queue/worker-shutdown": [
        "src/mycel/queue/inflight.py",
    ],
    "agents/analyst-sql": [
        "src/mycel/agents/tools/query.py",
        "src/mycel/agents/tools/work.py",
    ],
    "agents/anatomy": [
        "src/mycel/agents/core/base.py",
        "src/mycel/agents/registry.py",
        "src/mycel/agents/schemas.py",
        "src/mycel/agents/specialists/",
        "src/mycel/agents/core/deps.py",
        "src/mycel/agents/core/config.py",
        "src/mycel/agents/__init__.py",
        "src/mycel/agents/core/__init__.py",
    ],
    "agents/budget-limits": [
        "src/mycel/llm/budget.py",
        "src/mycel/infra/redis/budgets.py",
        "src/mycel/llm/__init__.py",
    ],
    "agents/charts": [
        "src/mycel/agents/core/charts.py",
    ],
    "agents/gemini-signatures": [
        "src/mycel/agents/core/signatures.py",
    ],
    "agents/guards": [
        "src/mycel/agents/core/guards.py",
    ],
    "agents/jira-writes": [
        "src/mycel/plugins/jira/tools.py",
        "src/mycel/plugins/jira/writes.py",
        "src/mycel/infra/redis/drafts.py",
    ],
    "agents/mcp": [
        "src/mycel/mcp/",
        "config/mcp/",
    ],
    "agents/model-source": [
        "src/mycel/agents/core/model_source.py",
        "src/mycel/agents/core/model_builder.py",
        "src/mycel/llm/router.py",
        "config/litellm/",
    ],
    "agents/orchestrator-delegation": [
        "src/mycel/agents/tools/delegate.py",
    ],
    "agents/own-model-keys": [
        "src/mycel/agents/core/own_endpoint.py",
        "src/mycel/agents/core/rotating.py",
        "src/mycel/infra/redis/key_rotation.py",
        "src/mycel/llm/quota.py",
        "src/mycel/domains/key_check.py",
        "src/mycel/infra/redis/key_checks.py",
    ],
    "agents/prompts": [
        "src/mycel/agents/prompts/",
    ],
    "agents/run-events": [
        "src/mycel/agents/core/emit.py",
        "src/mycel/events/",
    ],
    "agents/runner": [
        "src/mycel/agents/core/runner.py",
        "src/mycel/agents/core/exceptions.py",
    ],
    "agents/tools-and-chips": [
        "src/mycel/agents/core/chips.py",
        "src/mycel/agents/tools/__init__.py",
        "src/mycel/agents/tools/limits.py",
        "src/mycel/agents/tools/compute.py",
        "src/mycel/agents/tools/web_search.py",
        "src/mycel/plugins/google/mail.py",
        "src/mycel/plugins/google/calendar.py",
    ],
    "rag/citations": [
        "src/mycel/services/citations.py",
        "src/mycel/infra/redis/citations.py",
    ],
    "rag/embeddings-qdrant": [
        "src/mycel/infra/vectors/",
        "src/mycel/domains/index.py",
    ],
    "rag/ingest-pipeline": [
        "src/mycel/domains/ingest.py",
        "src/mycel/infra/documents/",
        "src/mycel/infra/postgres/documents.py",
        "src/mycel/infra/redis/document_events.py",
    ],
    "rag/search-and-answer": [
        "src/mycel/agents/tools/rag_search.py",
        "src/mycel/services/knowledge.py",
        "src/mycel/domains/chat_knowledge.py",
    ],
    "data/bronze-silver-gold": [
        "src/mycel/etl/normalize.py",
        "src/mycel/etl/promote.py",
        "src/mycel/etl/__init__.py",
        "src/mycel/services/transform.py",
        "src/mycel/infra/postgres/repositories/bronze.py",
        "src/mycel/infra/postgres/repositories/silver.py",
        "src/mycel/infra/postgres/repositories/gold.py",
        "src/mycel/infra/postgres/models/jira.py",
        "src/mycel/infra/postgres/models/gold.py",
    ],
    "data/connectors": [
        "src/mycel/sources/",
        "src/mycel/services/fetch.py",
    ],
    "data/dashboard": [
        "src/mycel/services/dashboard.py",
        "src/mycel/services/dashboards.py",
        "src/mycel/infra/postgres/repositories/gold_stats.py",
        "src/mycel/api/routes/dashboard.py",
        "src/mycel/services/gather.py",
        "src/mycel/services/analyze.py",
    ],
    "data/data-checks": [
        "src/mycel/etl/checks/",
        "src/mycel/services/check.py",
    ],
    "data/gold-access": [
        "src/mycel/infra/postgres/acl.py",
        "src/mycel/services/permission.py",
        "src/mycel/services/access.py",
    ],
    "data/sync-scheduler-locks": [
        "src/mycel/domains/sync.py",
        "src/mycel/scheduler/runner.py",
        "src/mycel/scheduler/__init__.py",
        "src/mycel/infra/postgres/locks.py",
    ],
    "storage/migrations": [
        "migrations/",
        "alembic.ini",
    ],
    "storage/object-storage": [
        "src/mycel/infra/objects/",
    ],
    "storage/postgres": [
        "src/mycel/infra/postgres/engine.py",
        "src/mycel/infra/postgres/session.py",
        "src/mycel/infra/postgres/__init__.py",
        "src/mycel/infra/postgres/repositories/_sql.py",
        "src/mycel/infra/postgres/repositories/__init__.py",
        "src/mycel/infra/postgres/models/base.py",
        "src/mycel/infra/postgres/models/__init__.py",
    ],
    "storage/redis-roles": [
        "src/mycel/infra/redis/client.py",
        "src/mycel/infra/redis/_kv.py",
        "src/mycel/infra/redis/__init__.py",
    ],
    "storage/smtp": [
        "src/mycel/infra/smtp.py",
    ],
    "api/errors-health": [
        "src/mycel/api/health.py",
    ],
    "api/middleware": [
        "src/mycel/api/middleware.py",
    ],
    "api/rate-limits": [
        "src/mycel/api/limits.py",
        "src/mycel/infra/redis/rate.py",
    ],
    "api/routes-map": [
        "src/mycel/api/routes/__init__.py",
        "src/mycel/api/routes/projects.py",
        "src/mycel/api/app.py",
        "src/mycel/api/__init__.py",
        "src/mycel/api/dependencies.py",
        "src/mycel/services/__init__.py",
    ],
    "platform/caching": [
        "src/mycel/domains/chat_cache.py",
        "src/mycel/infra/redis/answers.py",
    ],
    "platform/doctor": [
        "src/mycel/doctor/",
    ],
    "platform/http-clients": [
        "src/mycel/infra/http.py",
        "src/mycel/infra/__init__.py",
    ],
    "platform/logging-redaction": [
        "src/mycel/core/logging.py",
        "src/mycel/core/redact.py",
    ],
    "platform/metrics": [
        "src/mycel/observability/metrics.py",
        "src/mycel/observability/metrics_server.py",
        "src/mycel/observability/__init__.py",
    ],
    "platform/security": [
        "src/mycel/services/url_guard.py",
    ],
    "platform/streaming": [
        "src/mycel/api/routes/events.py",
        "src/mycel/infra/redis/streams.py",
    ],
    "platform/tracing": [
        "src/mycel/observability/tracing.py",
        "src/mycel/observability/turns.py",
        "src/mycel/observability/export.py",
    ],
    "web/answer-rendering": [
        "web/src/components/Answer.tsx",
        "web/src/components/AnswerMeta.tsx",
        "web/src/components/Trail.tsx",
        "web/src/components/Steps.tsx",
        "web/src/components/Chart.tsx",
        "web/src/components/Markdown.tsx",
        "web/src/components/LinkChip.tsx",
        "web/src/components/Json.tsx",
        "web/src/lib/citations.ts",
        "web/src/lib/toolLabel.ts",
        "web/src/lib/usage.ts",
    ],
    "web/architecture": [
        "web/src/main.tsx",
        "web/src/pages/Home.tsx",
        "web/src/components/Shell.tsx",
        "web/src/components/Sidebar.tsx",
        "web/src/styles/",
        "web/src/components/icons.tsx",
        "web/src/components/Demo.tsx",
        "web/src/components/UseCases.tsx",
        "web/src/components/Topics.tsx",
        "web/src/components/Flow.tsx",
        "web/src/hooks/useReveal.ts",
        "web/src/hooks/useHotkey.ts",
        "web/src/lib/theme.ts",
        "web/src/lib/links.ts",
    ],
    "web/ask-page-job-stream": [
        "web/src/pages/Ask.tsx",
        "web/src/hooks/useJobStream.ts",
        "web/src/hooks/useRun.ts",
        "web/src/hooks/useAskEffects.ts",
        "web/src/hooks/usePastTurns.ts",
        "web/src/context/ConversationsContext.tsx",
        "web/src/components/Composer.tsx",
        "web/src/components/ChipMenu.tsx",
        "web/src/components/ModelPicker.tsx",
        "web/src/components/Conversation.tsx",
        "web/src/components/ConversationRow.tsx",
        "web/src/components/PastTurns.tsx",
        "web/src/lib/buildConversation.ts",
        "web/src/components/Waiting.tsx",
    ],
    "web/dashboard-page": [
        "web/src/pages/dashboard/",
    ],
    "web/data-fetching-auth": [
        "web/src/api.ts",
        "web/src/lib/queryClient.ts",
        "web/src/context/auth.tsx",
        "web/src/pages/Login.tsx",
        "web/src/lib/useProjects.ts",
        "web/src/lib/types.ts",
        "web/src/components/Account.tsx",
    ],
    "web/knowledge-page": [
        "web/src/pages/Knowledge.tsx",
        "web/src/components/knowledge/",
        "web/src/hooks/useDocuments.ts",
    ],
    "web/settings-panels": [
        "web/src/components/panels/",
        "web/src/components/Modal.tsx",
        "web/src/components/Dialogs.tsx",
    ],
    "change/add-agent": [],
    "change/add-data-source": [],
    "change/add-gold-column": [],
    "change/add-host-model": [],
    "change/add-route": [],
    "change/add-setting": [],
    "change/add-tool": [],
    "change/evals": [
        "evals/",
    ],
    "change/testing": [
        "tests/",
        ".github/workflows/",
    ],
    "operate/deploy": [
        "scripts/compose/",
        "scripts/k8s/",
        "deploy/helm/",
        "deploy/inference/",
        "deploy/README.md",
        "Dockerfile",
    ],
    "operate/monitoring": [
        "deploy/monitoring/",
    ],
    "operate/run-locally": [
        "scripts/stack.sh",
        "scripts/dev/",
        "scripts/lib/",
        "scripts/README.md",
        "docker-compose.yml",
    ],
    "operate/runbooks": [
        "scripts/ops/",
    ],
    "operate/troubleshooting": [],
}


def owned(path: str) -> list[str]:
    return [
        page
        for page, owns in PAGES.items()
        if any(path == o or (o.endswith("/") and path.startswith(o)) for o in owns)
    ]


def sources() -> list[str]:
    found = []
    for base, suffixes in SCANNED.items():
        for path in (ROOT / base).rglob("*"):
            if (
                path.is_file()
                and path.suffix in suffixes
                and "__pycache__" not in path.parts
                and ".test." not in path.name
            ):
                found.append(str(path.relative_to(ROOT)))
    return sorted(found)


def main() -> int:
    files = sources()
    missing = [f for f in files if not owned(f)]
    doubled = {f: owned(f) for f in files if len(owned(f)) > 1}
    absent = [p for p in PAGES if not (DOCS / f"{p}.html").exists()]
    pages = {f"{p}.html" for p in PAGES} | KEPT
    strays = [
        str(f.relative_to(DOCS))
        for f in DOCS.rglob("*.html")
        if str(f.relative_to(DOCS)) not in pages
    ]
    print(f"{len(files)} files · {len(files) - len(missing)} owned · {len(PAGES)} pages")
    for label, items in (
        ("no page", missing),
        ("two pages", doubled),
        ("page file missing", absent),
        ("page not in PAGES", strays),
    ):
        for item in items:
            print(f"  {label}: {item}")
    return 1 if missing or doubled or absent or strays else 0


if __name__ == "__main__":
    sys.exit(main())
