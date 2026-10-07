#!/usr/bin/env bash
#
# Stores in compose, the three app processes on the host.
#
# The one mode where a code change is visible without a rebuild, which is why it is the
# default and why `up` starts no app profile in compose.
#
# The worker is not optional. Without it `POST /chat` returns a job id for work nobody
# picks up — which looks like a slow model rather than a missing process.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
source "$ROOT/scripts/lib/hostproc.sh"

require_env

log "starting containers: ${INFRA[*]}"
docker compose up -d "${INFRA[@]}"
wait_for_stores

log "applying migrations"
uv run alembic upgrade head

squatter=$(holder "$API_PORT")
if [[ -n $squatter ]] && ! alive api; then
  die "port $API_PORT is held by pid $squatter, which this script did not start.
     It answers requests, so the stack looks up while serving whatever code it was
     launched with. Stop it first:  kill $squatter"
fi

spawn api       uv run uvicorn --factory mycel.api.app:create_app --port "$API_PORT"
spawn worker    uv run python -m mycel.queue.consumer
spawn ingest    "$ROOT/scripts/dev/ingest-loop.sh"
spawn scheduler uv run python -m mycel.scheduler

# Each one, before waiting on the API: a worker that died on a bad import is invisible
# otherwise, and the stack would report itself up with nothing consuming the queue.
failed=0
for name in api worker ingest scheduler; do settled "$name" || failed=1; done
[[ $failed -eq 0 ]] || die "not everything came up — see the logs above, then: scripts/stack.sh dev down"

# `/health/live`, not `/health`: the router has a prefix and no route at the bare path, so
# probing it 404s forever while the API is perfectly healthy.
wait_for api "curl -sf http://localhost:$API_PORT/health/live"

echo
exec "$ROOT/scripts/dev/status.sh"
