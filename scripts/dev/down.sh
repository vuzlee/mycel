#!/usr/bin/env bash
#
# Stop the host processes and the stores. The data stays.
#
# `compose stop`, not `compose down`: `down` removes the containers. The volumes are named
# either way so bronze survives both, but a stopped container starts again in a second
# where a removed one re-runs its entrypoint from scratch.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
source "$ROOT/scripts/lib/hostproc.sh"

reap api
reap worker
reap scheduler
sweep
docker compose stop "${INFRA[@]}"
log "data kept in volumes mycel-pgdata, mycel-rabbitdata"
