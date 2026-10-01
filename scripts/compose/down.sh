#!/usr/bin/env bash
#
# Stop every container this project owns, whichever profile started it. The named volumes
# are untouched, so the data is still there on the next `up`.
#
# `--profile "*"` rather than a list: a profile added to docker-compose.yml later would
# otherwise keep running after a `down` that claimed to stop everything.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

docker compose --profile "*" stop
log "data kept in volumes mycel-pgdata, mycel-rabbitdata, mycel-qdrantdata"
