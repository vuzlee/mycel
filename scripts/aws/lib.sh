# Shared by scripts/aws/*. Sourced after lib/common.sh.

PROFILE=${AWS_PROFILE:-mycel}
REGION=eu-west-2
CLUSTER=mycel
CONTEXT=mycel-eks
SESSION_DIR="$ROOT/deploy/aws/session"
LIFE_HOURS=4
DOMAIN=mycel.sbs
LB_CHART=3.6.2

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

tf_out() { terraform -chdir="$SESSION_DIR" output -${2:-raw} "$1"; }

zone_id() { aws_ route53 list-hosted-zones-by-name --dns-name "$DOMAIN" --query 'HostedZones[0].Id' --output text; }

# The ALB's address, once the controller has made it; empty until then.
alb_host() { kube get ingress mycel-mycel -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null; }

# DOMAIN → the ALB, as an alias record. UPSERT or DELETE.
dns_change() {
  local action=$1 host=$2 zone
  zone=$(aws_ elbv2 describe-load-balancers \
    --query "LoadBalancers[?DNSName=='$host'].CanonicalHostedZoneId | [0]" --output text)
  aws_ route53 change-resource-record-sets --hosted-zone-id "$(zone_id)" --change-batch "$(cat <<JSON
{"Changes": [{"Action": "$action", "ResourceRecordSet": {"Name": "$DOMAIN", "Type": "A",
  "AliasTarget": {"HostedZoneId": "$zone", "DNSName": "$host", "EvaluateTargetHealth": false}}}]}
JSON
)" >/dev/null
}

dns_point() {
  local host i
  for i in $(seq 1 60); do host=$(alb_host); [[ -n $host ]] && break; sleep 5; done
  [[ -n $host ]] || die "the controller made no ALB in 5 min — kubectl describe ingress mycel-mycel"
  dns_change UPSERT "$host"
  log "$DOMAIN → $host"
}

# The record, then wait for every load balancer the controller made to go: the VPC
# cannot be deleted while one sits in it.
dns_unpoint_and_wait() {
  local name
  name=$(aws_ route53 list-resource-record-sets --hosted-zone-id "$(zone_id)" \
    --query "ResourceRecordSets[?Name=='$DOMAIN.' && Type=='A'].AliasTarget.DNSName | [0]" --output text)
  [[ $name == None || -z $name ]] || dns_change DELETE "${name%.}"
  local i
  for i in $(seq 1 60); do
    [[ -z $(aws_ elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerArn' --output text) ]] && return
    sleep 5
  done
  log "a load balancer is still there after 5 min; destroy may fail on the VPC"
}
