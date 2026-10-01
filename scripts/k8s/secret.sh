#!/usr/bin/env bash
#
# The Secret, built from .env with the four store URLs rewritten.
#
# THIS IS THE STEP THAT GOES WRONG. Inside a pod, `localhost` is that pod — so a
# DATABASE_URL copied straight out of .env looks completely correct and the pod dies with
# connection refused to itself. The rewrite below is the whole reason this is a script and
# not a line in the README.
#
# It carries the WHOLE file, settings as well as keys, because --from-env-file does. That
# matters beyond tidiness: in `envFrom`, secretRef is listed after configMapRef, so every
# value here wins over the ConfigMap. Anything that must hold regardless lives in the
# container's own `env:` — see templates/_helpers.tpl.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

require_env
need kubectl

# The host name minikube provides for reaching back out to the machine. Only minikube has
# it; a real cluster gets a real address, which is why it is a variable and not a constant
# in the chart.
HOST=${MYCEL_STORE_HOST:-host.minikube.internal}

tmp=$(mktemp)
# 600 before anything is written: this file holds every credential the deployment has, and
# mktemp's default is readable by the group on some systems.
chmod 600 "$tmp"
trap 'rm -f "$tmp"' EXIT

sed -E "s#(DATABASE_URL|RABBITMQ_URL|REDIS_URL|REDIS_CACHE_URL)=(.*)localhost#\1=\2$HOST#" \
  "$ROOT/.env" > "$tmp"

rewritten=$(grep -cE "^(DATABASE_URL|RABBITMQ_URL|REDIS_URL|REDIS_CACHE_URL)=.*$HOST" "$tmp" || true)
[[ $rewritten -eq 4 ]] || warn "only $rewritten of 4 store URLs name $HOST — check .env"

kubectl delete secret mycel-secrets --ignore-not-found >/dev/null
kubectl create secret generic mycel-secrets --from-env-file="$tmp" >/dev/null
log "mycel-secrets created, $(grep -cE '^[A-Z_]+=' "$tmp") keys, stores at $HOST"
