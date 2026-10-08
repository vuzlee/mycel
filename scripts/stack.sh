#!/usr/bin/env bash
#
# Run the stack. The modes differ in where the app runs, not in what it is.
#
#   scripts/stack.sh dev up|down|status|logs <name>      app on the host, stores in compose
#   scripts/stack.sh compose up [monitoring]|down|status  everything in containers
#   scripts/stack.sh k8s build|up [monitoring]|down [--all]|status|secret   chart on minikube
#
#   scripts/stack.sh doctor             what is configured, broken, or off
#   scripts/stack.sh sync [--refetch]   one Jira sync now

set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

usage() {
  sed -n '3,10p' "${BASH_SOURCE[0]}" | sed 's/^#\s\?//'
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

  -h|--help|help) usage 0 ;;
  *) printf '\033[31mxx\033[0m unknown: %s\n\n' "$mode" >&2; usage ;;
esac
