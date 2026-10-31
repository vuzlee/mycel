#!/usr/bin/env bash
#
# One session on EKS (HLD 123): cluster, stores, app. ~15 min, then ~$0.33 an hour.
#
#   scripts/stack.sh aws up [--tag <sha>]    images of that commit, default HEAD
#
# The cluster expires in 4 h; `aws extend <h>` moves it, `aws down` ends it.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

require_env
require_login
need kubectl
need helm

TAG=$(git rev-parse HEAD)
[[ ${1:-} == "--tag" ]] && TAG=$2
[[ -f "$ROOT/.env.aws" ]] || die ".env.aws is missing — copy .env.aws.example and set the passwords"

user=$(sed -n 's/^DOCKERHUB_USERNAME=//p' "$ROOT/.env" | tail -1)
[[ -n $user ]] || die "DOCKERHUB_USERNAME is not in .env"
curl -sf "https://hub.docker.com/v2/repositories/$user/mycel/tags/$TAG" >/dev/null \
  || die "no image $user/mycel:$TAG — push the commit and wait for the Release run"

log "terraform apply (~12 min)"
started=$(date +%s)
echo "owner_cidr = \"$(curl -s https://checkip.amazonaws.com)/32\"" > "$SESSION_DIR/terraform.tfvars"
tf_init
terraform -chdir="$SESSION_DIR" apply -input=false -auto-approve >/dev/null
set_expiry "$LIFE_HOURS"

aws_ eks update-kubeconfig --name "$CLUSTER" --alias "$CONTEXT" >/dev/null
kubectl config use-context "$CONTEXT" >/dev/null
kube wait --for=condition=Ready node --all --timeout=300s >/dev/null
log "node ready after $(( ($(date +%s) - started) / 60 )) min"

# .env with the session's passwords laid over it; the later line wins in env_value
# and in --from-env-file.
env_file=$(mktemp)
chmod 600 "$env_file"
trap 'rm -f "$env_file"' EXIT
cat "$ROOT/.env" "$ROOT/.env.aws" > "$env_file"

ENV_FILE=$env_file "$ROOT/scripts/k8s/stores-up.sh" --images "$user" --tag "$TAG"
log "up in $(( ($(date +%s) - started) / 60 )) min — next: scripts/stack.sh aws forward"
