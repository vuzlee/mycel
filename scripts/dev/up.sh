#!/usr/bin/env bash
# Stores in compose, the three app processes on the host.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
source "$ROOT/scripts/lib/hostproc.sh"

require_env

start_stores

migrate

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
failed=0
for name in api worker ingest scheduler; do settled "$name" || failed=1; done
[[ $failed -eq 0 ]] || die "not everything came up — see the logs above, then: scripts/stack.sh dev down"

# `/health/live`, not `/health`: the router has a prefix and no route at the bare path, so
wait_for api "curl -sf http://localhost:$API_PORT/health/live"

echo
exec "$ROOT/scripts/dev/status.sh"
