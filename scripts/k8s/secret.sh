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

# Postgres and RabbitMQ hosts come from the chart; only the Redis URLs carry one.
sed -E "s#(REDIS_URL|REDIS_CACHE_URL)=(.*)localhost#\1=\2$HOST#" \
  "$ROOT/.env" | grep -v '^LITELLM_MASTER_KEY=' > "$tmp"

rewritten=$(grep -cE "^(REDIS_URL|REDIS_CACHE_URL)=.*$HOST" "$tmp" || true)
[[ $rewritten -eq 2 ]] || warn "only $rewritten of 2 Redis URLs name $HOST — check .env"

kubectl delete secret mycel-secrets --ignore-not-found >/dev/null
kubectl create secret generic mycel-secrets --from-env-file="$tmp" >/dev/null
log "mycel-secrets created, $(grep -cE '^[A-Z_]+=' "$tmp") keys, stores at $HOST"
