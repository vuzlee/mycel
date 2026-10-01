#!/usr/bin/env bash
#
# Remove the release. The cluster keeps running, and so do the stores.
#
#   scripts/stack.sh k8s down          uninstall the chart
#   scripts/stack.sh k8s down --all    ... and stop minikube and the stores
#
# The Secret goes with the release even though Helm did not create it: it was built from
# this machine's .env by scripts/k8s/secret.sh, and leaving it behind means the next
# install silently uses credentials from whenever it was last written.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

need kubectl

ALL=false
[[ ${1:-} == "--all" ]] && ALL=true

if helm status mycel >/dev/null 2>&1; then
  log "uninstalling the release"
  helm uninstall mycel
else
  log "no release called mycel"
fi

kubectl delete secret mycel-secrets --ignore-not-found >/dev/null
log "secret removed"

if $ALL; then
  log "stopping minikube"
  minikube stop
  docker compose stop "${INFRA[@]}"
  log "data kept in volumes mycel-pgdata, mycel-rabbitdata"
fi
