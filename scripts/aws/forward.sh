#!/usr/bin/env bash
#
# The only way in: api on localhost:8000, Grafana on localhost:3000. Ctrl-C stops both.
# A forward that drops (pod restart, idle timeout) is started again.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need kubectl

keep() {
  while true; do
    kube port-forward "svc/$1" "$2:$2" >/dev/null 2>&1 || true
    warn "$1 forward dropped, again in 2 s"
    sleep 2
  done
}

keep mycel-mycel-api 8000 &
keep mycel-mycel-grafana 3000 &
trap 'kill $(jobs -p) 2>/dev/null' EXIT
log "app http://localhost:8000/app · Grafana http://localhost:3000 · Ctrl-C to stop"
wait
