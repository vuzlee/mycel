#!/usr/bin/env bash
#
# The chart, on minikube.
#
#   scripts/stack.sh k8s up              three application pods
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

if ! minikube status --format '{{.Host}}' 2>/dev/null | grep -q Running; then
  log "starting minikube"
  minikube start --driver=docker
fi

# nginx rather than whatever is default: values-minikube.yaml names it, and an Ingress
# whose class nobody serves stays pending forever without saying why.
if ! kubectl get ingressclass nginx >/dev/null 2>&1; then
  log "enabling the ingress addon"
  minikube addons enable ingress
fi

log "starting the stores in compose — they live outside the cluster on purpose"
docker compose up -d "${INFRA[@]}"
wait_for_stores

minikube image ls 2>/dev/null | grep -q 'mycel:dev' \
  || die "mycel:dev is not on the node — scripts/stack.sh k8s build"

"$ROOT/scripts/k8s/secret.sh"

args=(upgrade --install mycel "$ROOT/deploy/helm/mycel"
      -f "$ROOT/deploy/helm/mycel/values-minikube.yaml")
$MONITORING && args+=(--set monitoring.enabled=true)

log "helm ${args[*]:0:3}"
helm "${args[@]}"

# `--for=condition=Ready` on everything this release owns. The migration hook has already
# run by the time helm returns, so a pod still not ready here is a pod that is actually
# failing rather than one that has not been scheduled.
log "waiting for the pods"
kubectl wait --for=condition=Ready pod \
  -l "app.kubernetes.io/instance=mycel" --timeout=180s \
  || die "not every pod became ready — kubectl get pods, then kubectl logs <pod>"

echo
exec "$ROOT/scripts/k8s/status.sh"
