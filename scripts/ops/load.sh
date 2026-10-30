#!/usr/bin/env bash
#
# Signed-in reads under load, with k6 in docker. No model is called.
#
#   scripts/stack.sh load [compose|k8s] [vus] [seconds] [routes]
#
#   scripts/stack.sh load                       compose, 50 VUs, 30 s, the default mix
#   scripts/stack.sh load k8s 300 45            through the minikube ingress
#   scripts/stack.sh load compose 50 20 /models one route
#
# A throwaway session for the first user is written to the database and deleted on exit,
# so the dev database keeps nothing. Prints k6's summary: rps, latency, one line per status.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

K6_IMAGE=grafana/k6:0.54.0
# What a signed-in page reads. /projects is in on purpose: it held two connections at once
# (MYC-249). /health/ready is out: it has its own connection, and its fast answers would pull
# the percentiles below what a person sees.
DEFAULT_ROUTES=/auth/me,/projects,/conversations,/documents,/models

target=${1:-compose}
vus=${2:-50}
seconds=${3:-30}
routes=${4:-$DEFAULT_ROUTES}

case "$target" in
  compose) base="http://localhost:$API_PORT" host_header="" ;;
  k8s)
    need minikube
    base="http://$(minikube ip)" host_header=mycel.local ;;
  *) die "unknown target: $target (compose | k8s)" ;;
esac

need docker
pg=$(cid postgres)
[[ -n $pg ]] || die "postgres is not running — scripts/stack.sh compose up"
psql() { docker exec "$pg" psql -U mycel -d mycel -tAqc "$1"; }

user=$(psql "select min(id) from app.user")
[[ -n $user ]] || die "no user to sign in as — sign in once through the app first"

token=load$(openssl rand -hex 28)
psql "insert into app.session (id, user_id, expires_at) values ('$token', $user, now() + interval '1 hour')"
trap 'psql "delete from app.session where id = '"'$token'"'" >/dev/null' EXIT

curl -sf -o /dev/null ${host_header:+-H "Host: $host_header"} -b "mycel_session=$token" "$base/auth/me" \
  || die "$base/auth/me does not answer 200 with the load session"

log "$target · $vus VUs · ${seconds}s · $routes"
docker run --rm --network host -v "$ROOT/scripts/ops/load:/load:ro" \
  -e BASE="$base" -e HOST_HEADER="$host_header" -e TOKEN="$token" \
  -e VUS="$vus" -e DURATION="${seconds}s" -e ROUTES="$routes" \
  "$K6_IMAGE" run -q /load/reads.js 2>&1 \
  | grep -E 'http_reqs|http_req_duration|status_' | grep -v ': 0 '
