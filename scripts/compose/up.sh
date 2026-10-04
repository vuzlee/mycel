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
check_legacy

# `api` and `app` are two profiles for one thing — the api container carries `api`, the
# worker and scheduler carry `app` — so both are always on. The rest are asked for.
profiles=(--profile api --profile app)
for extra in "$@"; do
  case "$extra" in
    monitoring|local-llm) profiles+=(--profile "$extra") ;;
    *) die "unknown profile: $extra (monitoring | local-llm)" ;;
  esac
done

log "starting containers: ${INFRA[*]}"
docker compose up -d "${INFRA[@]}"
wait_for_stores

# From the host, against the host's .env: the app containers have not started yet, and one
# of them running this would be the race described above.
log "applying migrations"
uv run alembic upgrade head

log "starting the application"
docker compose "${profiles[@]}" up -d

wait_for api "curl -sf http://localhost:$API_PORT/health/live"
echo
exec "$ROOT/scripts/compose/status.sh"
