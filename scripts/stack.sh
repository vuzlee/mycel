#!/usr/bin/env bash
#
# The dev stack, in one command.
#
#   scripts/stack.sh up        bring everything up and wait until it answers
#   scripts/stack.sh down      stop everything and sweep strays, keep the data
#   scripts/stack.sh status    what is running, and on which port
#   scripts/stack.sh logs api  follow one host process (api | worker | scheduler)
#   scripts/stack.sh sync      run one Jira sync now, without waiting for the tick
#   scripts/stack.sh relocate  move Postgres onto the named volume, keeping the data
#   scripts/stack.sh restore   load a dump back in, if a relocate was interrupted
#
# Containers use `docker run` with named volumes rather than the compose CLI, which is not
# installed here. Named volumes are the point: `down` then `up` keeps bronze, so a stack
# restart never costs a re-fetch of updates Telegram has already dropped.
#
# The API, the worker and the scheduler run on the host, not in containers: they are what
# is being edited, and `uv run` picks up a change without a rebuild.
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

log()  { printf '\033[36m==\033[0m %s\n' "$*"; }
die()  { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

# --- containers ------------------------------------------------------------------------

# Created only if absent, started if merely stopped, left alone if already running — so
# `up` is safe to run again, which is what makes it the single command to remember.
#
# `docker inspect` on a container that does not exist writes an empty line to *stdout* and
# then fails, so `$(... || echo missing)` yields "\nmissing" — which matches neither arm and
# falls through to `docker start`, on a container there is nothing to start. So existence is
# asked as its own question, by exit status, before asking what state the thing is in.
#
# `-f ''` rather than `-q`: this docker has no `-q` on `inspect`, and a flag the daemon
# rejects exits non-zero too — which would read as "does not exist" for every container and
# turn every `up` into a name conflict.
container() {
  local name=$1; shift
  if ! docker inspect -f '' "$name" >/dev/null 2>&1; then
    log "$name creating"
    docker run -d --name "$name" "$@" >/dev/null
    return
  fi
  case "$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null)" in
    running) log "$name already up" ;;
    *)       log "$name starting";  docker start "$name" >/dev/null ;;
  esac
}

# A container whose data is not on the named volume this script expects.
#
# Worth checking because the mismatch is invisible until it costs something: the container
# keeps its data across `down`/`up` either way, so nothing looks wrong. What breaks is
# `docker rm` — an anonymous volume outlives its container as an unnamed heap of bytes that
# nothing can mount again, and the data is gone in every sense that matters.
#
# Older versions of this script created containers without `-v`, so a machine that has been
# running this stack for a while very likely has one.
check_volume() {
  local name=$1 expect=$2 actual
  docker inspect "$name" >/dev/null 2>&1 || return 0
  actual=$(docker inspect "$name" -f '{{range .Mounts}}{{.Name}}{{end}}' 2>/dev/null || true)
  [[ $actual == "$expect" ]] && return 0
  log "warning: $name stores data on ${actual:-a bind mount}, not $expect"
  log "         it survives down/up, but a docker rm would strand it."
  case "$name" in
    mycel-pg) log "         to move it, keeping the rows:  scripts/stack.sh relocate" ;;
    # Not worth a dump. What RabbitMQ keeps is queue definitions and whatever is waiting in
    # them, and `queue/broker.py` declares the queues on connect. Recreating the container
    # costs the dead-letter queue and nothing else.
    *)        log "         to move it, losing whatever is queued:  docker rm -f $name" ;;
  esac
}

start_containers() {
  check_volume mycel-pg mycel-pgdata
  check_volume mycel-rabbit mycel-rabbitdata

  container mycel-pg \
    -e POSTGRES_USER=mycel -e POSTGRES_PASSWORD=mycel -e POSTGRES_DB=mycel \
    -p "$PG_PORT:5432" -v mycel-pgdata:/var/lib/postgresql/data \
    postgres:16-alpine

  # `--tmpfs /data` because the image declares `VOLUME /data`, and docker honours that by
  # creating an anonymous volume per container — one more orphan on every recreate, for a
  # server started with `--save ''` that writes nothing to it. tmpfs gives the declaration
  # somewhere to point that disappears with the container.
  container mycel-redis \
    -p 6379:6379 --tmpfs /data redis:7-alpine \
    redis-server --save '' --appendonly no --maxmemory 256mb --maxmemory-policy noeviction

  container mycel-rabbit \
    -e RABBITMQ_DEFAULT_USER=mycel -e RABBITMQ_DEFAULT_PASS=mycel \
    -p 5672:5672 -p 15672:15672 -v mycel-rabbitdata:/var/lib/rabbitmq \
    rabbitmq:3.13-management-alpine
}

# Ready means "answers a query", not "the container is up". Postgres accepts TCP several
# seconds before it will serve one, and alembic run in that window fails.
wait_for() {
  local name=$1 probe=$2 tries=${3:-60}
  for _ in $(seq "$tries"); do
    if eval "$probe" >/dev/null 2>&1; then log "$name ready"; return 0; fi
    sleep 1
  done
  die "$name did not come up in ${tries}s — try: docker logs $name"
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
  rm -f "$RUN/$name.pid"
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
  rm -f "$RUN/$name.pid"
  return 1
}

reap() {
  local name=$1 pid
  alive "$name" || { rm -f "$RUN/$name.pid"; return; }
  pid=$(cat "$RUN/$name.pid")
  log "$name stopping (pid $pid)"
  # The group, not the process: `uv run` is a parent whose child does the work.
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  if kill -0 "$pid" 2>/dev/null; then
    log "$name ignored TERM, sending KILL"
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$RUN/$name.pid"
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

  start_containers
  wait_for postgres "docker exec mycel-pg pg_isready -U mycel"
  wait_for redis    "docker exec mycel-redis redis-cli ping"
  # `check_port_connectivity`, not `ping`: ping only asks whether the Erlang node is alive,
  # and it answers yes a good few seconds before the AMQP listener accepts a connection.
  # In that window the worker starts, is reset by the broker mid-handshake, and dies —
  # which reads as a broken worker rather than a stack started half a second too early.
  wait_for rabbitmq "docker exec mycel-rabbit rabbitmq-diagnostics -q check_port_connectivity" 90

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

cmd_down() {
  reap api
  reap worker
  reap scheduler
  sweep
  for c in mycel-pg mycel-redis mycel-rabbit; do
    docker stop "$c" >/dev/null 2>&1 && log "$c stopped" || true
  done
  log "data kept in volumes mycel-pgdata, mycel-rabbitdata"
}

cmd_status() {
  local name port project squatter api_state
  printf '\033[1m%-12s %-9s %s\033[0m\n' SERVICE STATE WHERE
  for c in "mycel-pg:$PG_PORT" mycel-redis:6379 mycel-rabbit:5672; do
    name=${c%:*}; port=${c#*:}
    printf '%-12s %-9s localhost:%s\n' "${name#mycel-}" \
      "$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || echo missing)" "$port"
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

  project=$(docker exec mycel-pg psql -U mycel -d mycel -tAc \
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

# Move Postgres off an anonymous volume and onto `mycel-pgdata`, keeping the data.
#
# Through a SQL dump rather than by copying files: a dump is readable, restores into any
# Postgres, and can be kept. Copying the data directory would be faster and would also
# carry over whatever is wrong with it.
#
# Redis is not moved — it holds a live stream and a cache, both rebuilt. RabbitMQ is not
# moved either: a queue with nothing in it has nothing to lose, and this runs with the
# stack down.
cmd_relocate() {
  local mount dump="$RUN/relocate-$(date +%Y%m%d-%H%M%S).sql"

  docker inspect mycel-pg >/dev/null 2>&1 || die "mycel-pg does not exist — just run: scripts/stack.sh up"
  mount=$(docker inspect mycel-pg -f '{{range .Mounts}}{{.Name}}{{end}}')
  [[ $mount == mycel-pgdata ]] && { log "mycel-pg is already on mycel-pgdata, nothing to do"; return; }

  log "starting mycel-pg to read it"
  docker start mycel-pg >/dev/null 2>&1 || true
  wait_for postgres "docker exec mycel-pg pg_isready -U mycel"

  mkdir -p "$RUN"
  log "dumping to ${dump#"$ROOT/"}"
  docker exec mycel-pg pg_dump -U mycel -d mycel --clean --if-exists >"$dump"
  [[ -s $dump ]] || die "the dump came out empty — stopping before anything is removed"
  log "dump is $(wc -l <"$dump") lines"

  log "replacing the container"
  docker stop mycel-pg >/dev/null
  docker rm mycel-pg >/dev/null
  start_containers
  wait_for postgres "docker exec mycel-pg pg_isready -U mycel"

  cmd_restore "$dump"

  log "done — mycel-pg now stores data on mycel-pgdata"
  log "the dump is kept at ${dump#"$ROOT/"}; the old anonymous volume is still there, unused"
  log "list what is unused with: docker volume ls -f dangling=true"
}

# Load a dump back into Postgres. `relocate` calls this as its last step, and you can call
# it yourself when something interrupted that — the container ends up on the right volume
# with the schema but no rows, and the dump is still sitting in `.run/`.
#
# Defaults to the newest `relocate-*.sql`, because that is the one an interrupted move left
# behind. The dump is `--clean --if-exists`, so loading it twice is not a problem.
cmd_restore() {
  local dump=${1:-}
  if [[ -z $dump ]]; then
    dump=$(ls -1t "$RUN"/relocate-*.sql 2>/dev/null | head -1 || true)
    [[ -n $dump ]] || die "no dump in .run/ — pass one: scripts/stack.sh restore <file.sql>"
  fi
  [[ -s $dump ]] || die "$dump is missing or empty"

  wait_for postgres "docker exec mycel-pg pg_isready -U mycel"
  log "restoring ${dump#"$ROOT/"}"
  docker exec -i mycel-pg psql -U mycel -d mycel -q <"$dump" >/dev/null
  log "restored — $(docker exec mycel-pg psql -U mycel -d mycel -tAc \
    'select count(*) from gold.work_item') rows in gold.work_item"
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
  relocate) cmd_relocate ;;
  restore)  cmd_restore "${2:-}" ;;
  *)        die "unknown command: $1 (up | down | restart | status | logs <name> | sync | relocate | restore)" ;;
esac
