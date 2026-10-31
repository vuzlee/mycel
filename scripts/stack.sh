#!/usr/bin/env bash
#
# Run the stack. The modes differ in where the app runs, not in what it is.
#
#   scripts/stack.sh dev up|down|status|logs <name>      app on the host, stores in compose
#   scripts/stack.sh compose up [monitoring]|down|status  everything in containers
#   scripts/stack.sh k8s build|up [monitoring]|down [--all]|status|secret   chart on minikube
#   scripts/stack.sh k8s stores-up [--images <user>] [--tag <sha>]       stores in the cluster too (AWS)
#
#   scripts/stack.sh doctor             what is configured, broken, or off
#   scripts/stack.sh sync [--refetch]   one Jira sync now
#   scripts/stack.sh replay [dlq [N]]   count parked jobs, or send them back
#   scripts/stack.sh broker-rebuild     fresh broker data dir, users kept (queues must be empty)
#   scripts/stack.sh gateway-key [usd]  the app's scoped gateway key, from the master key
#   scripts/stack.sh web-smoke [base]   the batch A web fixes in headless Chrome
#   scripts/stack.sh load [compose|k8s|seed|reset] [rates] [s] [routes]   reads at an arrival rate, to the SLO

set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

usage() {
  sed -n '3,15p' "${BASH_SOURCE[0]}" | sed 's/^#\s\?//'
  exit "${1:-1}"
}

run() {
  local script=$1; shift
  [[ -x $script ]] || { printf '\033[31mxx\033[0m no such command\n' >&2; usage; }
  exec "$script" "$@"
}

mode=${1:-dev}
shift || true

case "$mode" in
  dev|compose|k8s)
    # `up` by default, so `stack.sh dev` and `stack.sh k8s` do the obvious thing.
    action=${1:-up}
    shift || true
    run "$HERE/$mode/$action.sh" "$@"
    ;;

  doctor)       run "$HERE/ops/doctor.sh" "$@" ;;
  sync)         run "$HERE/ops/sync.sh" "$@" ;;
  replay)       run "$HERE/ops/replay.sh" "$@" ;;
  broker-rebuild) run "$HERE/ops/broker-rebuild.sh" "$@" ;;
  gateway-key)  run "$HERE/ops/gateway-key.sh" "$@" ;;
  web-smoke)    run "$HERE/ops/web-smoke.sh" "$@" ;;
  load)         run "$HERE/ops/load.sh" "$@" ;;

  -h|--help|help) usage 0 ;;
  *) printf '\033[31mxx\033[0m unknown: %s\n\n' "$mode" >&2; usage ;;
esac
