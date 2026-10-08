#!/usr/bin/env bash
# Every container this project owns, including the ones a profile did not start.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

docker compose --profile "*" ps \
  --format 'table {{.Service}}\t{{.State}}\t{{.Ports}}' 2>/dev/null \
  || die "compose has nothing for this project — scripts/stack.sh compose up"

print_links
if docker compose ps --format '{{.Service}}' 2>/dev/null | grep -q '^grafana$'; then
  echo "grafana    http://localhost:3000"
fi
