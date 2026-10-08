#!/usr/bin/env bash
#
# The chart, on minikube.
#
#   scripts/stack.sh k8s up              four application pods: api, worker, ingest, scheduler
#   scripts/stack.sh k8s up monitoring   ... and Prometheus, Loki, Promtail, Grafana
#
# THE STORES STAY OUTSIDE THE CLUSTER and this script starts them in compose. Postgres,
# RabbitMQ and Redis as StatefulSets is the painful part of Kubernetes — storage classes,
# a volume per pod identity — and it proves nothing the chart is meant to prove. The pods
# reach them at host.minikube.internal; see scripts/k8s/secret.sh for the trap in that.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

require_env
need minikube
need helm
need kubectl

MONITORING=false
for extra in "$@"; do
  case "$extra" in
    monitoring) MONITORING=true ;;
    *) die "unknown option: $extra (monitoring)" ;;
  esac
done

if ! minikube_running; then
  log "starting minikube"
  minikube start --driver=docker
fi

# nginx rather than whatever is default: values-minikube.yaml names it, and an Ingress
# whose class nobody serves stays pending forever without saying why.
if ! kubectl get ingressclass nginx >/dev/null 2>&1; then
  log "enabling the ingress addon"
  minikube addons enable ingress
fi

start_stores

images=$(minikube image ls 2>/dev/null)
for image in mycel:dev mycel-ingest:dev; do
  grep -qE "(^|/)$image\$" <<<"$images" \
    || die "$image is not on the node — scripts/stack.sh k8s build"
done

"$ROOT/scripts/k8s/secret.sh"

args=(upgrade --install mycel "$ROOT/deploy/helm/mycel"
      -f "$ROOT/deploy/helm/mycel/values-minikube.yaml")
$MONITORING && args+=(--set monitoring.enabled=true)

log "helm ${args[*]:0:3}"
helm "${args[@]}"

# Each Deployment's rollout, not every pod with the release label: a migration Job that
# failed on an earlier attempt leaves its pods behind in Error, and they are never Ready.
# Waiting on them times out over a release that is in fact running.
log "waiting for the rollouts"
for d in $(kubectl get deploy -l "app.kubernetes.io/instance=mycel" -o name); do
  kubectl rollout status "$d" --timeout=300s \
    || die "$d did not roll out — kubectl get pods, then kubectl logs <pod>"
done

echo
exec "$ROOT/scripts/k8s/status.sh"
