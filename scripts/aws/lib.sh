# Shared by scripts/aws/*. Sourced after lib/common.sh.

PROFILE=${AWS_PROFILE:-mycel}
REGION=eu-west-2
CLUSTER=mycel
CONTEXT=mycel-eks
SESSION_DIR="$ROOT/deploy/aws/session"
LIFE_HOURS=4

aws_() { aws --profile "$PROFILE" --region "$REGION" "$@"; }
kube() { kubectl --context "$CONTEXT" "$@"; }

require_login() {
  need aws
  aws_ sts get-caller-identity >/dev/null 2>&1 \
    || die "not signed in — aws sso login --profile $PROFILE"
}

state_bucket() { echo "mycel-tfstate-$(aws_ sts get-caller-identity --query Account --output text)"; }

tf_init() {
  need terraform
  terraform -chdir="$SESSION_DIR" init -input=false -reconfigure \
    -backend-config="bucket=$(state_bucket)" -backend-config="profile=$PROFILE" >/dev/null
}

cluster_arn() { aws_ eks describe-cluster --name "$CLUSTER" --query cluster.arn --output text 2>/dev/null; }

set_expiry() {
  local at
  at=$(date -u -d "+$1 hours" +%FT%TZ)
  aws_ eks tag-resource --resource-arn "$(cluster_arn)" --tags "mycel-expires=$at"
  log "expires $at (UTC); the reaper deletes it after that"
}
