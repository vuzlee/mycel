#!/usr/bin/env bash
# Shared by every script under scripts/. Sourced, never run.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"

RUN="$ROOT/.run"
PG_PORT=5433
API_PORT=8000

# Named so a new compose service is never started by accident.
INFRA=(postgres redis rabbitmq qdrant minio litellm)

log()  { printf '\033[36m==\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "$1 is not installed${2:+ — $2}"; }

require_env() {
  [[ -f "$ROOT/.env" ]] || die ".env is missing — copy .env.example and fill in the tokens"
}

cid() { docker compose ps -q "$1" 2>/dev/null | head -1; }

# Ready means it answers, not that the container is up.
wait_for() {
  local name=$1 probe=$2 tries=${3:-60}
  for _ in $(seq "$tries"); do
    if eval "$probe" >/dev/null 2>&1; then log "$name ready"; return 0; fi
    sleep 1
  done
  die "$name did not come up in ${tries}s — try: docker compose logs $name"
}

start_stores() {
  log "starting containers: ${INFRA[*]}"
  docker compose up -d "${INFRA[@]}"
  wait_for postgres "docker exec $(cid postgres) pg_isready -U mycel"
  wait_for redis    "docker exec $(cid redis) redis-cli ping"
  # `ping` answers before the AMQP listener accepts connections.
  wait_for rabbitmq "docker exec $(cid rabbitmq) rabbitmq-diagnostics -q check_port_connectivity" 90
  wait_for qdrant   "curl -sf http://localhost:6333/readyz"
  wait_for minio    "curl -sf http://localhost:9000/minio/health/ready"
  wait_for litellm  "curl -sf http://localhost:4000/health/liveliness" 90
}

stop_stores() {
  docker compose stop "${INFRA[@]}"
  log "data kept in volumes: $(data_volumes)"
}

data_volumes() {
  docker compose config --format json \
    | python3 -c "import json,sys; print(' '.join(v['name'] for v in json.load(sys.stdin)['volumes'].values() if 'data' in v['name']))"
}

migrate() {
  log "applying migrations"
  uv run alembic upgrade head
}

# Pid listening on a port, or nothing. Never fails: a free port is the normal case.
holder() {
  ss -ltnp 2>/dev/null \
    | awk -v p=":$1\$" '$4 ~ p {print $NF}' \
    | grep -o 'pid=[0-9]*' \
    | head -1 | cut -d= -f2 || true
}

synced_project() {
  local pg; pg=$(cid postgres)
  [[ -n $pg ]] || return 0
  docker exec "$pg" psql -U mycel -d mycel -tAc \
    'select project from gold.work_item limit 1' 2>/dev/null | tr -d '[:space:]' || true
}

print_links() {
  local project; project=$(synced_project)
  echo
  echo "sign in    http://localhost:$API_PORT/app/login"
  if [[ -n $project ]]; then
    echo "dashboard  http://localhost:$API_PORT/app/dashboard?project=$project"
  else
    echo "dashboard  http://localhost:$API_PORT/app/dashboard  (nothing synced yet)"
  fi
  echo "api docs   http://localhost:$API_PORT/docs"
}

minikube_running() { minikube status --format '{{.Host}}' 2>/dev/null | grep -q Running; }
