#!/usr/bin/env bash
#
# Is a cluster up, until when, for how long so far, and what this month has cost.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

require_login

read -r status created expires < <(aws_ eks describe-cluster --name "$CLUSTER" \
  --query 'cluster.[status,createdAt,tags."mycel-expires"]' --output text 2>/dev/null || echo "none - -")
if [[ $status == none ]]; then
  log "no cluster: costs nothing now"
else
  hours=$(( ($(date +%s) - $(date -d "$created" +%s)) / 3600 ))
  log "cluster $status since $created (${hours} h, ~\$$(awk "BEGIN{printf \"%.2f\", ($hours + 1) * 0.33}") so far)"
  log "expires $expires (UTC)"
fi

# Cost Explorer charges $0.01 a call and lags up to a day; credits not taken off.
if [[ ${1:-} == "--bill" ]]; then
  month=$(date -u +%Y-%m-01)
  today=$(date -u +%F)
  [[ $month == "$today" ]] && { log "first of the month: nothing billed yet"; exit 0; }
  aws --profile "$PROFILE" --region us-east-1 ce get-cost-and-usage \
    --time-period "Start=$month,End=$today" --granularity MONTHLY --metrics UnblendedCost \
    --filter '{"Not":{"Dimensions":{"Key":"RECORD_TYPE","Values":["Credit"]}}}' \
    --query 'ResultsByTime[0].Total.UnblendedCost.Amount' --output text \
    | xargs printf '\033[36m==\033[0m this month before credits: $%.2f\n'
fi
