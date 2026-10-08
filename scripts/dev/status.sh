#!/usr/bin/env bash
# What is running, and on which port.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
source "$ROOT/scripts/lib/hostproc.sh"

printf '\033[1m%-12s %-9s %s\033[0m\n' SERVICE STATE WHERE
for c in "postgres:$PG_PORT" redis:6379 rabbitmq:5672; do
  name=${c%:*}; port=${c#*:}
  # `|| echo missing` would never fire: `compose ps` on a service it does not manage exits
  state=$(docker compose ps --format '{{.State}}' "$name" 2>/dev/null | head -1 || true)
  printf '%-12s %-9s localhost:%s\n' "$name" "${state:-missing}" "$port"
done

api_state=$(alive api && echo running || echo stopped)
squatter=$(holder "$API_PORT")
if [[ $api_state == stopped && -n $squatter ]]; then
  api_state=foreign
  printf '%-12s %-9s localhost:%s — pid %s, not ours\n' api "$api_state" "$API_PORT" "$squatter"
else
  printf '%-12s %-9s localhost:%s\n' api "$api_state" "$API_PORT"
fi
printf '%-12s %-9s consuming the job queue\n' worker \
  "$(alive worker && echo running || echo stopped)"
printf '%-12s %-9s parsing and embedding documents\n' ingest \
  "$(alive ingest && echo running || echo stopped)"
printf '%-12s %-9s every SYNC_INTERVAL_SECONDS\n' scheduler \
  "$(alive scheduler && echo running || echo stopped)"

print_links
if [[ $api_state == foreign ]]; then
  echo
  echo "warning    pid $squatter holds :$API_PORT and this script did not start it."
  echo "           Requests are being served by whatever code it was launched with."
  echo "           kill $squatter && scripts/stack.sh dev up"
fi
