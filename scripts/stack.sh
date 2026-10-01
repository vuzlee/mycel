#!/usr/bin/env bash
#
# The stack, in one command. Three ways to run the same application.
#
#   scripts/stack.sh dev up|down|status|logs <name>
#   scripts/stack.sh compose up [monitoring] [vectors] | down | status
#   scripts/stack.sh k8s build | up [monitoring] | down [--all] | status | secret
#
#   scripts/stack.sh doctor               what is configured, broken, or off on purpose
#   scripts/stack.sh sync [--refetch]     one Jira sync now
#   scripts/stack.sh grants               the two least-privilege roles
#   scripts/stack.sh grafana-sync [--check]
#
# THE THREE MODES DIFFER IN WHERE THE APPLICATION RUNS, not in what it is:
#
#   dev      api/worker/scheduler on the host under `uv run`, stores in compose.
#            The only mode where a code change is visible without a rebuild, which is
#            why it is the default.
#   compose  all three in containers, running the IMAGE. For checking the thing CI
#            builds, rather than for writing code against.
#   k8s      the chart on minikube. Stores stay OUTSIDE the cluster, in compose.
#
# `sync`, `grants` and `grafana-sync` take no mode: they talk to the data or the repo,
# and both are the same whichever way the app is running.
#
# This file dispatches and nothing else. Each mode owns its own directory, so a change to
# the Kubernetes path cannot break the dev one by sharing a variable with it — which is
# what the one 372-line script this replaced made easy.

set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

usage() {
  sed -n '3,28p' "${BASH_SOURCE[0]}" | sed 's/^#\s\?//'
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

  doctor)       run "$HERE/data/doctor.sh" "$@" ;;
  sync)         run "$HERE/data/sync.sh" "$@" ;;
  grants)       run "$HERE/data/grants.sh" "$@" ;;
  grafana-sync) run "$HERE/data/grafana-sync.sh" "$@" ;;

  # The old flat commands, which muscle memory and several READMEs still use.
  up|down|status|logs|restart)
    printf '\033[33m!!\033[0m `stack.sh %s` is now `stack.sh dev %s`\n' "$mode" "$mode" >&2
    [[ $mode == restart ]] && { "$HERE/dev/down.sh"; run "$HERE/dev/up.sh"; }
    run "$HERE/dev/$mode.sh" "$@"
    ;;
  refetch)
    printf '\033[33m!!\033[0m `stack.sh refetch` is now `stack.sh sync --refetch`\n' >&2
    run "$HERE/data/sync.sh" --refetch
    ;;

  -h|--help|help) usage 0 ;;
  *) printf '\033[31mxx\033[0m unknown: %s\n\n' "$mode" >&2; usage ;;
esac
