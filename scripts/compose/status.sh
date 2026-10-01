#!/usr/bin/env bash
#
# Every container this project owns, including the ones a profile did not start.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

docker compose --profile "*" ps \
  --format 'table {{.Service}}\t{{.State}}\t{{.Ports}}' 2>/dev/null \
  || die "compose has nothing for this project — scripts/stack.sh compose up"

project=$(synced_project)
echo
echo "sign in    http://localhost:$API_PORT/app/login"
if [[ -n $project ]]; then
  echo "dashboard  http://localhost:$API_PORT/app/dashboard?project=$project"
else
  echo "dashboard  http://localhost:$API_PORT/app/dashboard  (nothing synced yet)"
fi
echo "api docs   http://localhost:$API_PORT/docs"
if docker compose ps --format '{{.Service}}' 2>/dev/null | grep -q '^grafana$'; then
  echo "grafana    http://localhost:3000"
fi
