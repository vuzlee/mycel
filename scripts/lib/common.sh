#!/usr/bin/env bash
#
# What every script under scripts/ needs. Sourced, never run.
#
# One copy of `die` rather than three, and — more to the point — one copy of `wait_for`.
# Ready means "answers a query", not "the container is up": Postgres accepts TCP several
# seconds before it will serve one, and alembic in that window fails with a message about
# the database rather than about the wait.

set -euo pipefail

# The repository root, whatever directory the caller was in. Every path below is relative
# to it, so `scripts/dev/up.sh` and `cd scripts && ./dev/up.sh` behave the same.
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"

RUN="$ROOT/.run"

PG_PORT=5433
API_PORT=8000

#: The compose services that are infrastructure. Named rather than left to a bare `up`, so
#: adding a service to docker-compose.yml does not silently start it here.
INFRA=(postgres redis rabbitmq qdrant minio)

log()  { printf '\033[36m==\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "$1 is not installed${2:+ — $2}"; }

require_env() {
  [[ -f "$ROOT/.env" ]] || die ".env is missing — copy .env.example and fill in the tokens"
}

# Whatever compose called the container for a service. Every `docker exec` goes through
# this rather than hardcoding a name: the name is compose's to choose, and it changes with
# the project name and the replica number.
cid() { docker compose ps -q "$1" 2>/dev/null | head -1; }

# Compose's own healthchecks say the same thing, but `up -d` without `--wait` does not
# block on them, and `--wait` gives one opaque timeout for all three instead of naming the
# one that hung.
wait_for() {
  local name=$1 probe=$2 tries=${3:-60}
  for _ in $(seq "$tries"); do
    if eval "$probe" >/dev/null 2>&1; then log "$name ready"; return 0; fi
    sleep 1
  done
  die "$name did not come up in ${tries}s — try: docker compose logs $name"
}

wait_for_stores() {
  wait_for postgres "docker exec $(cid postgres) pg_isready -U mycel"
  wait_for redis    "docker exec $(cid redis) redis-cli ping"
  # `check_port_connectivity`, not `ping`: ping only asks whether the Erlang node is alive,
  # and it answers yes a good few seconds before the AMQP listener accepts a connection. In
  # that window a worker starts, is reset mid-handshake, and dies — which reads as a broken
  # worker rather than a stack started half a second too early.
  wait_for rabbitmq "docker exec $(cid rabbitmq) rabbitmq-diagnostics -q check_port_connectivity" 90
  wait_for qdrant   "curl -sf http://localhost:6333/readyz"
  wait_for minio    "curl -sf http://localhost:9000/minio/health/ready"
}

# Containers from before compose, started by name with `docker run`. They hold the same
# ports and mount the same volumes, so compose cannot start its own beside them — and the
# failure reads as a port conflict rather than as two stacks.
check_legacy() {
  local found=()
  for c in mycel-pg mycel-redis mycel-rabbit; do
    docker inspect -f '' "$c" >/dev/null 2>&1 && found+=("$c")
  done
  [[ ${#found[@]} -eq 0 ]] && return 0
  die "these containers predate compose and hold the same ports: ${found[*]}
     The data is on the named volumes, which docker-compose.yml adopts, so removing
     the containers keeps every row:  docker rm -f ${found[*]}
     Then run this again."
}

# Whoever is listening on a port, if anyone. Tells "nothing is running" apart from
# "something we did not start is running" — the second reads as the first in `status`,
# while curl happily answers from a process old enough to be missing half the routes.
#
# Empty output, never a failure. `grep` exits 1 on no match, and under `set -e` a command
# substitution that fails takes the whole script with it, so a free port would kill the
# caller. A port with nobody on it is the normal case, not an error.
holder() {
  ss -ltnp 2>/dev/null \
    | awk -v p=":$1\$" '$4 ~ p {print $NF}' \
    | grep -o 'pid=[0-9]*' \
    | head -1 | cut -d= -f2 || true
}

# The project any synced data belongs to, for printing a dashboard link. Empty when
# nothing has synced, which the caller words rather than guessing at.
synced_project() {
  local pg; pg=$(cid postgres)
  [[ -n $pg ]] || return 0
  docker exec "$pg" psql -U mycel -d mycel -tAc \
    'select project from gold.work_item limit 1' 2>/dev/null | tr -d '[:space:]' || true
}
