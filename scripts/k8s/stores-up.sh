#!/usr/bin/env bash
#
# Everything in the cluster: the stores as release mycel-stores, then the app with
# values-aws.yaml. The same steps on minikube (to prove it at $0) and on EKS.
#
#   scripts/stack.sh k8s stores-up [--images <dockerhub-user>] [--tag <sha>]
#
# Without --images the app runs the images `k8s build` loaded into minikube.
# With DOCKERHUB_USERNAME and DOCKERHUB_TOKEN in .env every pod pulls with that login;
# without them pulls are anonymous, capped at 10 an hour per address.
#
# Order matters:
#   1. stores Secret and LiteLLM ConfigMap   the stores read them at start
#   2. helm install mycel-stores, wait       the app's migrate hook needs Postgres up
#   3. gateway key                           LiteLLM's database is new each time
#   4. app Secret, helm install mycel        store URLs point at the Services

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

require_env
need helm
need kubectl
need curl
need jq

USER_IMAGES="" TAG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --images) USER_IMAGES=$2; shift 2 ;;
    --tag) TAG=$2; shift 2 ;;
    *) die "unknown option: $1 (--images <user>, --tag <sha>)" ;;
  esac
done

env_value() { sed -n "s/^$1=//p" "$ROOT/.env" | tail -1; }

# --- 0. one Docker Hub login for every pull
pull=""
if [[ -n $(env_value DOCKERHUB_USERNAME) && -n $(env_value DOCKERHUB_TOKEN) ]]; then
  log "Docker Hub pull secret"
  kubectl create secret docker-registry dockerhub --docker-server=https://index.docker.io/v1/ \
    --docker-username="$(env_value DOCKERHUB_USERNAME)" --docker-password="$(env_value DOCKERHUB_TOKEN)" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  pull=dockerhub
else
  warn "no DOCKERHUB_USERNAME / DOCKERHUB_TOKEN in .env: pulls are anonymous"
fi

# --- 1. what the stores read
log "stores Secret and LiteLLM config"
kubectl create secret generic mycel-stores-secrets --from-env-file="$ROOT/.env" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl create configmap mycel-litellm-config --from-file="$ROOT/config/litellm/" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

# --- 2. the stores
log "helm mycel-stores"
helm upgrade --install mycel-stores "$ROOT/deploy/helm/mycel-stores" --set "pullSecret=$pull" >/dev/null
for d in postgres rabbitmq redis redis-cache qdrant minio litellm; do
  kubectl rollout status "deploy/$d" --timeout=300s >/dev/null \
    || die "$d did not come up — kubectl logs deploy/$d"
  log "$d ready"
done

# --- 3. the app's key to the gateway, made with the master key
log "gateway key"
kubectl port-forward svc/litellm 14000:4000 >/dev/null 2>&1 &
forward=$!
trap 'kill $forward 2>/dev/null || true' EXIT
for _ in $(seq 20); do curl -sf http://localhost:14000/health/liveliness >/dev/null && break; sleep 1; done
models=$(uv run python -c "
from mycel.core.config import get_settings
import json; print(json.dumps([m.name for m in get_settings().host_models]))")
key=$(curl -fsS http://localhost:14000/key/generate \
  -H "Authorization: Bearer $(env_value LITELLM_MASTER_KEY)" -H "Content-Type: application/json" \
  -d "{\"key_alias\": \"mycel-app\", \"models\": $models, \"max_budget\": 10, \"budget_duration\": \"30d\"}" \
  | jq -r .key)
[[ $key == sk-* ]] || die "the gateway did not return a key"
kill $forward 2>/dev/null || true

# --- 4. the app: .env minus what only the gateway holds, plus the new key and Redis URLs
log "app Secret"
tmp=$(mktemp)
chmod 600 "$tmp"
trap 'rm -f "$tmp"; kill $forward 2>/dev/null || true' EXIT
grep -vE '^(LITELLM_MASTER_KEY|LITELLM_API_KEY|REDIS_URL|REDIS_CACHE_URL|DEFAULT_MODEL_API_KEY|DOCKERHUB_[A-Z]+)=' \
  "$ROOT/.env" > "$tmp"
{
  echo "LITELLM_API_KEY=$key"
  echo "REDIS_URL=redis://redis:6379/0"
  echo "REDIS_CACHE_URL=redis://redis-cache:6379/0"
} >> "$tmp"
kubectl create secret generic mycel-secrets --from-env-file="$tmp" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

args=(upgrade --install mycel "$ROOT/deploy/helm/mycel"
      -f "$ROOT/deploy/helm/mycel/values-aws.yaml" --set "image.pullSecret=$pull")
if [[ -n $USER_IMAGES ]]; then
  args+=(--set "image.repository=$USER_IMAGES/mycel" --set "ingest.image.repository=$USER_IMAGES/mycel-ingest")
  [[ -n $TAG ]] && args+=(--set "image.tag=$TAG")
else
  # Images loaded by `k8s build`: never pulled; the stores and monitoring still are.
  args+=(--set image.tag=dev --set image.pullPolicy=Never)
fi

log "helm mycel"
helm "${args[@]}" >/dev/null
for d in $(kubectl get deploy -l "app.kubernetes.io/instance=mycel" -o name); do
  kubectl rollout status "$d" --timeout=600s >/dev/null \
    || die "$d did not roll out — kubectl get pods, then kubectl logs <pod>"
  log "${d#deployment.apps/} ready"
done

echo
log "open it: kubectl port-forward svc/mycel-mycel-api 8000:8000"
