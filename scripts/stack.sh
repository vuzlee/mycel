#!/usr/bin/env bash
#
# The dev stack, in one command.
#
#   scripts/stack.sh up        bring everything up and wait until it answers
#   scripts/stack.sh down      stop everything and sweep strays, keep the data
#   scripts/stack.sh status    what is running, and on which port
#   scripts/stack.sh logs api  follow one host process (api | worker | scheduler)
#   scripts/stack.sh sync      run one Jira sync now, without waiting for the tick
#   scripts/stack.sh grants    apply migrations/grants.sql, the two least-privilege roles
#
# The containers are `docker compose up -d`, not a `docker run` per service. This script
# used to spell all three out in bash because the compose CLI was not installed here; it
# is now, and docker-compose.yml already declares the same images, ports and volumes. One
# definition, and the one that prod reads.
#
# The API, the worker and the scheduler run on the host, not in containers: they are what
# is being edited, and `uv run` picks up a change without a rebuild. That is the whole
# reason this script still exists next to compose — and why `up` starts no app profile.
#
# The worker is not optional. Without it `POST /reports` and `POST /reports/summary` both
# return a job id for work nobody ever picks up — which looks like a slow model rather
# than a missing process.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT=$(pwd)
RUN="$ROOT/.run"

PG_PORT=5433
API_PORT=8000

# The three compose services that are infrastructure. Named rather than left to a bare
# `up`, so adding a service to the file does not silently start it here.
INFRA=(postgres redis rabbitmq)

log()  { printf '\033[36m==\033[0m %s\n' "$*"; }
die()  { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

# --- containers ------------------------------------------------------------------------

# Whatever compose called the container for a service. Every `docker exec` below goes
# through this rather than hardcoding `mycel-pg`: the name is compose's to choose, and it
# changes with the project name and the replica number.
cid() { docker compose ps -q "$1" 2>/dev/null | head -1; }

# Containers from the era before compose, started by name with `docker run`. They hold the
# same ports and mount the same volumes, so compose cannot start its own beside them — and
# the failure reads as a port conflict rather than as two stacks.
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

# Ready means "answers a query", not "the container is up". Postgres accepts TCP several
# seconds before it will serve one, and alembic run in that window fails. Compose's own
# healthchecks say the same thing, but `up -d` without `--wait` does not block on them and
# `--wait` gives one opaque timeout for all three instead of naming the one that hung.
wait_for() {
  local name=$1 probe=$2 tries=${3:-60}
  for _ in $(seq "$tries"); do
    if eval "$probe" >/dev/null 2>&1; then log "$name ready"; return 0; fi
    sleep 1
  done
  die "$name did not come up in ${tries}s — try: docker compose logs $name"
}

# --- host processes ----------------------------------------------------------------------

alive() { [[ -f "$RUN/$1.pid" ]] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }

# Whoever is listening on a port, if anyone. Used to tell "nothing is running" apart from
# "something we did not start is running" — the second reads as the first in `status`,
# while `curl` happily answers from a process old enough to be missing half the routes.
#
# Empty output, never a failure. `grep` exits 1 on no match, and under `set -e` a command
# substitution that fails takes the whole script with it — so on a free port this used to
# kill `up` right after the migrations and truncate `status` mid-table. A port with nobody
# on it is the normal case, not an error.
holder() {
  ss -ltnp 2>/dev/null \
    | awk -v p=":$1\$" '$4 ~ p {print $NF}' \
    | grep -o 'pid=[0-9]*' \
    | head -1 | cut -d= -f2 || true
}

# The pid written here must be the process that actually runs, and it must be a process
# group leader — `reap` signals the whole group, because `uv run` execs a child and killing
# only the parent leaves that child alive.
#
# `setsid cmd &` gives neither. In a non-interactive shell the background job is not a group
# leader, so setsid forks: `$!` names the setsid wrapper, which exits at once. The pid file
# then holds a dead number, `alive` says stopped, and `down` kills nothing — which is how a
# machine ends up with three orphaned workers.
#
# So the inner shell writes its own `$$` and then `exec`s. After setsid it is the session
# and group leader, and `exec` means the pid does not change.
spawn() {
  local name=$1; shift
  if alive "$name"; then log "$name already up (pid $(cat "$RUN/$name.pid"))"; return; fi
  mkdir -p "$RUN"
  rm -f "${RUN:?}/${name:?}.pid"
  setsid bash -c 'echo $$ >"$1"; shift; exec "$@"' _ \
    "$RUN/$name.pid" "$@" >"$RUN/$name.log" 2>&1 </dev/null &
  disown

  # The pid file is written by a process that has not been scheduled yet.
  local pid=""
  for _ in $(seq 40); do
    [[ -s "$RUN/$name.pid" ]] && { pid=$(cat "$RUN/$name.pid"); break; }
    sleep 0.1
  done
  [[ -n $pid ]] || die "$name never started — see .run/$name.log"
  log "$name started (pid $pid, log: .run/$name.log)"
}

# Started, and still there a moment later. A process that dies on a bound port or a bad
# import exits within milliseconds, and without this the stack reports itself up while two
# thirds of it is a log file nobody reads.
settled() {
  local name=$1
  sleep 2
  alive "$name" && return 0
  printf '\033[31mxx\033[0m %s died immediately:\n' "$name" >&2
  sed 's/^/     /' "$RUN/$name.log" | tail -15 >&2
  rm -f "${RUN:?}/${name:?}.pid"
  return 1
}

reap() {
  local name=$1 pid
  alive "$name" || { rm -f "${RUN:?}/${name:?}.pid"; return; }
  pid=$(cat "$RUN/$name.pid")
  log "$name stopping (pid $pid)"
  # The group, not the process: `uv run` is a parent whose child does the work.
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  if kill -0 "$pid" 2>/dev/null; then
    log "$name ignored TERM, sending KILL"
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "${RUN:?}/${name:?}.pid"
}

# Anything of ours that no pid file points at. Earlier versions of this script wrote the
# wrong pid, and a crashed `up` can leave a half-started process behind, so `down` cannot
# assume its own bookkeeping is complete.
#
# Matched on this checkout's own interpreter path, never on the module name alone: another
# clone of this repo in another directory is somebody else's stack, and `down` here must
# not reach into it.
sweep() {
  local pids
  pids=$(pgrep -f "$ROOT/.venv/bin/.*(uvicorn|mycel\.)" 2>/dev/null || true)
  pids="$pids $(pgrep -f "^uv run .*(uvicorn --factory mycel|mycel\.queue\.consumer|mycel\.scheduler)" 2>/dev/null || true)"
  pids=$(echo "$pids" | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -un || true)
  [[ -n $pids ]] || return 0

  log "sweeping $(echo "$pids" | wc -w) stray process(es)"
  # shellcheck disable=SC2086
  kill -TERM $pids 2>/dev/null || true
  for _ in $(seq 10); do
    pgrep -f "$ROOT/.venv/bin/.*(uvicorn|mycel\.)" >/dev/null 2>&1 || break
    sleep 0.5
  done
  # shellcheck disable=SC2086
  kill -KILL $pids 2>/dev/null || true
}

# --- commands -----------------------------------------------------------------------------

cmd_up() {
  [[ -f .env ]] || die ".env is missing — copy .env.example and fill in the tokens"
  check_legacy

  log "starting containers: ${INFRA[*]}"
  docker compose up -d "${INFRA[@]}"

  wait_for postgres "docker exec $(cid postgres) pg_isready -U mycel"
  wait_for redis    "docker exec $(cid redis) redis-cli ping"
  # `check_port_connectivity`, not `ping`: ping only asks whether the Erlang node is alive,
  # and it answers yes a good few seconds before the AMQP listener accepts a connection.
  # In that window the worker starts, is reset by the broker mid-handshake, and dies —
  # which reads as a broken worker rather than a stack started half a second too early.
  wait_for rabbitmq "docker exec $(cid rabbitmq) rabbitmq-diagnostics -q check_port_connectivity" 90

  log "applying migrations"
  uv run alembic upgrade head

  local squatter
  squatter=$(holder "$API_PORT")
  if [[ -n $squatter ]] && ! alive api; then
    die "port $API_PORT is held by pid $squatter, which this script did not start.
     It answers requests, so the stack looks up while serving whatever code it was
     launched with. Stop it first:  kill $squatter"
  fi

  spawn api       uv run uvicorn --factory mycel.api.app:create_app --port "$API_PORT"
  spawn worker    uv run python -m mycel.queue.consumer
  spawn scheduler uv run python -m mycel.scheduler

  # Each one, before waiting on the API: a worker that died on a bad import is invisible
  # otherwise, and the stack would report itself up with nothing consuming the queue.
  local failed=0 name
  for name in api worker scheduler; do settled "$name" || failed=1; done
  [[ $failed -eq 0 ]] || die "not everything came up — see the logs above, then: scripts/stack.sh down"

  # `/health/live`, not `/health`: the router has a prefix and no route at the bare path,
  # so probing it 404s forever while the API is perfectly healthy.
  wait_for api "curl -sf http://localhost:$API_PORT/health/live"

  echo
  cmd_status
}

# `compose stop`, not `compose down`: `down` removes the containers, and this keeps them.
# The volumes are external either way, so bronze survives both — but a stopped container
# starts again in a second, where a removed one re-runs the entrypoint from scratch.
cmd_down() {
  reap api
  reap worker
  reap scheduler
  sweep
  docker compose stop "${INFRA[@]}"
  log "data kept in volumes mycel-pgdata, mycel-rabbitdata"
}

cmd_status() {
  local name port project squatter api_state pg state
  printf '\033[1m%-12s %-9s %s\033[0m\n' SERVICE STATE WHERE
  for c in "postgres:$PG_PORT" redis:6379 rabbitmq:5672; do
    name=${c%:*}; port=${c#*:}
    # `|| echo missing` would never fire: `compose ps` on a service it does not manage
    # exits 0 with no output, so the empty string has to be caught rather than the status.
    state=$(docker compose ps --format '{{.State}}' "$name" 2>/dev/null | head -1 || true)
    printf '%-12s %-9s localhost:%s\n' "$name" "${state:-missing}" "$port"
  done
  api_state=$(alive api && echo running || echo stopped)
  squatter=$(holder "$API_PORT")
  if [[ $api_state == stopped && -n $squatter ]]; then
    api_state=foreign
    printf '%-12s %-9s localhost:%s — pid %s, not ours\n' api "$api_state" "$API_PORT" "$squatter"
  else
    printf '%-12s %-9s localhost:%s\n' api "$api_state" "$API_PORT"
  fi
  printf '%-12s %-9s consuming the job queue\n' worker \
    "$(alive worker && echo running || echo stopped)"
  printf '%-12s %-9s every SYNC_INTERVAL_SECONDS\n' scheduler \
    "$(alive scheduler && echo running || echo stopped)"

  pg=$(cid postgres)
  project=""
  [[ -n $pg ]] && project=$(docker exec "$pg" psql -U mycel -d mycel -tAc \
    'select project from gold.work_item limit 1' 2>/dev/null | tr -d '[:space:]' || true)
  echo
  echo "sign in    http://localhost:$API_PORT/app/login"
  if [[ -n $project ]]; then
    echo "dashboard  http://localhost:$API_PORT/app/dashboard?project=$project"
  else
    echo "dashboard  http://localhost:$API_PORT/app/dashboard  (nothing synced yet)"
  fi
  echo "api docs   http://localhost:$API_PORT/docs"
  if [[ $api_state == foreign ]]; then
    echo
    echo "warning    pid $squatter holds :$API_PORT and this script did not start it."
    echo "           Requests are being served by whatever code it was launched with."
    echo "           kill $squatter && scripts/stack.sh up"
  fi
}

# The per-schema roles. Separate from `up` because it needs a superuser and because it is
# not idempotent in the way `up` is — it revokes, and a deployment decides when to.
#
# Passwords come from the environment so they are not in the shell history, and the file
# does the rest. `alembic upgrade head` first: `GRANT ... ON ALL TABLES` only reaches
# tables that exist, and `ALTER DEFAULT PRIVILEGES` covers the ones a later migration adds.
cmd_grants() {
  local app_pw=${MYCEL_APP_PASSWORD:-} etl_pw=${MYCEL_ETL_PASSWORD:-} pg
  [[ -n $app_pw && -n $etl_pw ]] || die "set MYCEL_APP_PASSWORD and MYCEL_ETL_PASSWORD first"

  pg=$(cid postgres)
  [[ -n $pg ]] || die "postgres is not running — scripts/stack.sh up"
  wait_for postgres "docker exec $pg pg_isready -U mycel"
  log "applying migrations first — grants only reach tables that exist"
  uv run alembic upgrade head

  docker cp migrations/grants.sql "$pg:/tmp/grants.sql" >/dev/null
  docker exec "$pg" psql -U mycel -d mycel \
    -v app_password="$app_pw" -v etl_password="$etl_pw" -f /tmp/grants.sql
  docker exec "$pg" rm -f /tmp/grants.sql
  log "mycel_app reads gold and owns app; mycel_etl writes bronze, silver and gold"
}

cmd_logs() { tail -f "$RUN/${1:?which process: api, worker or scheduler}.log"; }

cmd_sync() {
  uv run python -c "
import asyncio
from mycel.domains.sync import sync_jira
print(asyncio.run(sync_jira()))"
}

case "${1:-up}" in
  up)       cmd_up ;;
  down)     cmd_down ;;
  restart)  cmd_down; cmd_up ;;
  status)   cmd_status ;;
  logs)     cmd_logs "${2:-}" ;;
  sync)     cmd_sync ;;
  grants)   cmd_grants ;;
  *)        die "unknown command: $1 (up | down | restart | status | logs <name> | sync | grants)" ;;
esac
