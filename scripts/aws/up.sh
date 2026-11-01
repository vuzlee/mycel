#!/usr/bin/env bash
#
# One session on EKS (HLD 123, 128): cluster, stores, app at https://mycel.sbs.
# ~20 min, then ~$0.37 an hour.
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

# .env with the session's passwords laid over it, one line per key:
# --from-env-file refuses a key twice.
env_file=$(mktemp)
chmod 600 "$env_file"
trap 'rm -f "$env_file"' EXIT
awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/ { line[$1] = $0; if (!($1 in seen)) { seen[$1]; order[++n] = $1 } }
  END { for (i = 1; i <= n; i++) print line[order[i]] }' "$ROOT/.env" "$ROOT/.env.aws" > "$env_file"

# The controller first: the app's Ingress is what it turns into an ALB.
log "aws load balancer controller"
helm repo add eks https://aws.github.io/eks-charts >/dev/null 2>&1 || true
helm --kube-context "$CONTEXT" upgrade --install aws-load-balancer-controller \
  eks/aws-load-balancer-controller --version "$LB_CHART" -n kube-system \
  --set clusterName="$CLUSTER" --set region="$REGION" \
  --set vpcId="$(tf_out vpc_id)" --set "defaultTags.mycel-session=$CLUSTER" \
  --wait >/dev/null

cert=$(aws_ acm list-certificates --certificate-statuses ISSUED \
  --query "CertificateSummaryList[?DomainName=='$DOMAIN'].CertificateArn | [0]" --output text)
[[ $cert == arn:* ]] || die "no issued certificate for $DOMAIN — check the name servers (batch 130)"
cidrs=$(tf_out public_subnet_cidrs json | tr -d '[]" ')
HELM_EXTRA="--set ingress.annotations.alb\.ingress\.kubernetes\.io/certificate-arn=$cert \
--set api.networkPolicy.ingressCIDRs={$cidrs}" \
  ENV_FILE=$env_file "$ROOT/scripts/k8s/stores-up.sh" --images "$user" --tag "$TAG"

dns_point
log "up in $(( ($(date +%s) - started) / 60 )) min — https://$DOMAIN · Grafana: scripts/stack.sh aws forward"
