#!/usr/bin/env bash
#
# The batch A web fixes, driven in headless Chrome against a running api. Calls no model.
#
#   scripts/stack.sh web-smoke [base]      base defaults to http://localhost:8000

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

need node
need docker
dir="${TMPDIR:-/tmp}/mycel-web-smoke"
if [[ ! -d $dir/node_modules/puppeteer-core ]]; then
  log "installing puppeteer-core into $dir"
  mkdir -p "$dir" && (cd "$dir" && npm init -y >/dev/null && npm i puppeteer-core@23.11.1 >/dev/null)
fi

out=$(PUPPETEER_DIR="$dir" node "$ROOT/scripts/dev/web-smoke.mjs" "${1:-http://localhost:8000}") || status=$?
echo "$out"
account=$(grep -o 'smoke-[0-9]*@example.com' <<<"$out" | tail -1)
if [[ -n $account ]]; then
  docker exec "$(cid postgres)" psql -U mycel -qtAc "delete from app.\"user\" where email = '$account'" >/dev/null
  log "removed $account"
fi
exit "${status:-0}"
