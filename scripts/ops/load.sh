#!/usr/bin/env bash
#
# Signed-in reads under load, with k6 in docker, in steps of arrival rate until the SLO
# breaks. No model is called.
#
#   scripts/stack.sh load [compose|k8s] [rates] [seconds] [routes]
#
#   scripts/stack.sh load                           compose, 50,100,…,600 rps, 60 s a step
#   scripts/stack.sh load k8s 200,400,600,800 90    through the minikube ingress
#   scripts/stack.sh load compose 150 30 /models    one rate, one route
#   scripts/stack.sh load seed [users]              mycel_load at a real size; api moves to it
#   scripts/stack.sh load reset                     api back on the dev database
#
# Capacity is the last step that held the SLO. On the dev database a throwaway session for
# the first user is written and deleted on exit. On mycel_load each VU signs in as one of
# the seeded users, so caches and Postgres see many people, not one.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

K6_IMAGE=grafana/k6:0.54.0
# One Ask page load reads each of these once. /health/ready is out: it has its own
# connection, and its fast answers would pull the percentiles below what a person sees.
DEFAULT_ROUTES=/auth/me,/projects,/conversations,/documents,/models
DEFAULT_RATES=50,100,150,200,250,300,350,400,500,600
# Proposed 2026-10-30 (batch 122); k6 thresholds are built from these.
SLO_P95=${SLO_P95:-300}
SLO_P99=${SLO_P99:-1000}
SLO_ERRORS=${SLO_ERRORS:-0.001}
WARMUP=${WARMUP:-10s}
# Each step runs RUNS times; it holds only if every run does. The median p95 is shown.
RUNS=${RUNS:-3}
K6_CPUS=8-13

LOAD_DB=mycel_load
LOAD_COMPOSE=(-f "$ROOT/docker-compose.yml" -f "$ROOT/scripts/ops/load/compose.yml")

api_on() {
  docker compose "$@" --profile api up -d postgres api >/dev/null
  wait_for api "curl -sf http://localhost:$API_PORT/health/ready"
}

seed() {
  local users=${1:-2000} pg; pg=$(cid postgres)
  [[ -n $pg ]] || die "postgres is not running — scripts/stack.sh compose up"
  docker exec "$pg" psql -U mycel -d postgres -tAqc "select 1 from pg_database where datname = '$LOAD_DB'" \
    | grep -q 1 || docker exec "$pg" psql -U mycel -d postgres -qc "create database $LOAD_DB"
  log "migrating $LOAD_DB"
  POSTGRES_DB=$LOAD_DB uv run alembic upgrade head
  log "seeding $LOAD_DB: $users users"
  docker exec -i "$pg" psql -U mycel -d "$LOAD_DB" -q -v users="$users" -v convs=50 -v turns=10 \
    -v projects=20 -v items=50000 < "$ROOT/scripts/ops/load/seed.sql"
  docker exec "$pg" psql -U mycel -d "$LOAD_DB" -tAc \
    "select format('%s users · %s conversations · %s turns · %s work items', \
       (select count(*) from app.user), (select count(*) from app.conversation), \
       (select count(*) from app.turn), (select count(*) from gold.work_item))"
  api_on "${LOAD_COMPOSE[@]}"
}

case ${1:-} in
  seed)  shift; seed "$@"; exit ;;
  reset) api_on; log "api is on the dev database"; exit ;;
esac

target=${1:-compose}
rates=${2:-$DEFAULT_RATES}
seconds=${3:-60}
routes=${4:-$DEFAULT_ROUTES}

case "$target" in
  compose) base="http://localhost:$API_PORT" host_header="" ;;
  k8s)
    need minikube
    base="http://$(minikube ip)" host_header=mycel.local ;;
  *) die "unknown target: $target (compose | k8s)" ;;
esac

need docker
need jq
pg=$(cid postgres)
[[ -n $pg ]] || die "postgres is not running — scripts/stack.sh compose up"
db=$(docker exec "$(cid api)" printenv POSTGRES_DB 2>/dev/null || echo mycel)
psql() { docker exec "$pg" psql -U mycel -d "$db" -tAqc "$1"; }

if [[ $db == "$LOAD_DB" ]]; then
  users=$(psql "select count(*) from app.session where id like 'load-%'")
  (( users )) || die "$LOAD_DB has no seeded sessions — scripts/stack.sh load seed"
  token=load-1
else
  users=0
  user=$(psql "select min(id) from app.user")
  [[ -n $user ]] || die "no user to sign in as — sign in once through the app first"
  token=load$(openssl rand -hex 28)
  psql "insert into app.session (id, user_id, expires_at) values ('$token', $user, now() + interval '3 hours')"
  trap 'psql "delete from app.session where id = '"'$token'"'" >/dev/null' EXIT
fi

curl -sf -o /dev/null ${host_header:+-H "Host: $host_header"} -b "mycel_session=$token" "$base/auth/me" \
  || die "$base/auth/me does not answer 200 with the load session"

log "$target · $RUNS × ${seconds}s a step after ${WARMUP} warmup · SLO p95<${SLO_P95}ms p99<${SLO_P99}ms errors<${SLO_ERRORS}"
log "$routes · database $db · $(( users ? users : 1 )) user(s)"
printf '%6s %7s %8s %8s %8s %7s %8s  %-6s  %s  %s\n' rate rps p50 p95 p99 errors dropped slo 'p95 runs' statuses

step() {
  docker run --rm --network host --cpuset-cpus "$K6_CPUS" -v "$ROOT/scripts/ops/load:/load:ro" \
    -e BASE="$base" -e HOST_HEADER="$host_header" -e TOKEN="$token" -e USERS="$users" -e ROUTES="$routes" \
    -e RATE="$1" -e WARMUP="$WARMUP" -e DURATION="${seconds}s" \
    -e SLO_P95="$SLO_P95" -e SLO_P99="$SLO_P99" -e SLO_ERRORS="$SLO_ERRORS" \
    "$K6_IMAGE" run -q /load/reads.js 2>/dev/null | grep '^{"rate"' || true
}

held=0
for rate in ${rates//,/ }; do
  runs=""
  for _ in $(seq "$RUNS"); do
    one=$(step "$rate")
    [[ -n $one ]] || die "k6 printed no summary at $rate rps"
    runs+="$one"$'\n'
  done
  # The median run by p95, every run's p95 beside it, held only if all held.
  line=$(jq -sc 'sort_by(.p95) as $r | $r[(length/2|floor)]
    + {slo: all(.[]; .slo), p95s: ($r|map(.p95|floor)|join("/"))}' <<<"$runs")

  # shellcheck disable=SC2046
  printf '%6s %7s %6sms %6sms %6sms %6s%% %8s  %-6s  %s  %s\n' $(jq -r '[.rate, (.rps|floor), (.p50|floor),
    (.p95|floor), (.p99|floor), (.errors*1000|round/10), .dropped, (if .slo then "ok" else "BROKEN" end),
    .p95s, (.statuses|to_entries|map("\(.key):\(.value)")|join(","))] | @tsv' <<<"$line")

  [[ $(jq -r .slo <<<"$line") == true ]] || break
  held=$rate
done

if (( held )); then log "capacity: $held rps held the SLO"; else warn "no step held the SLO"; fi
