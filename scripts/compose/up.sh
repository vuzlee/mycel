#!/usr/bin/env bash
#
# Everything in containers, including the three app processes.
#
# The difference from `dev`: these run the IMAGE, so a code change needs a rebuild. Use it
# to check that the image itself works — the thing CI builds and the chart deploys — rather
# than to write code against.
#
#   scripts/stack.sh compose up                    stores + api + worker + scheduler
#   scripts/stack.sh compose up monitoring         ... and Prometheus, Loki, Grafana
#
# Migrations are run here rather than by an entrypoint: three app containers starting at
# once would each try, and the loser of that race reports a lock timeout rather than the
# real problem.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

require_env

# `api` and `app` are two profiles for one thing — the api container carries `api`, the
profiles=(--profile api --profile app)
for extra in "$@"; do
  case "$extra" in
    monitoring|local-llm) profiles+=(--profile "$extra") ;;
    *) die "unknown profile: $extra (monitoring | local-llm)" ;;
  esac
done

start_stores

migrate

log "starting the application"
docker compose "${profiles[@]}" up -d

wait_for api "curl -sf http://localhost:$API_PORT/health/live"
echo
exec "$ROOT/scripts/compose/status.sh"
