#!/usr/bin/env bash
# The Secret from .env, with the store URLs pointed out of the pod: inside a pod, localhost

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

require_env
need kubectl

# minikube's name for the host; a real cluster sets MYCEL_STORE_HOST.
HOST=${MYCEL_STORE_HOST:-host.minikube.internal}

tmp=$(mktemp)
# Every credential goes in here.
chmod 600 "$tmp"
trap 'rm -f "$tmp"' EXIT

sed -E "s#(MIGRATION_DATABASE_URL|DATABASE_URL|RABBITMQ_URL|REDIS_URL|REDIS_CACHE_URL)=(.*)localhost#\1=\2$HOST#" \
  "$ROOT/.env" > "$tmp"

rewritten=$(grep -cE "^(DATABASE_URL|RABBITMQ_URL|REDIS_URL|REDIS_CACHE_URL)=.*$HOST" "$tmp" || true)
[[ $rewritten -eq 4 ]] || warn "only $rewritten of 4 store URLs name $HOST — check .env"

kubectl delete secret mycel-secrets --ignore-not-found >/dev/null
kubectl create secret generic mycel-secrets --from-env-file="$tmp" >/dev/null
log "mycel-secrets created, $(grep -cE '^[A-Z_]+=' "$tmp") keys, stores at $HOST"
