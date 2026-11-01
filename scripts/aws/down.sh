#!/usr/bin/env bash
#
# End the session: releases, then terraform destroy, then a check that nothing tagged
# mycel-session is left. Every step skips when it is already done, so a rerun after a
# failure or after the reaper picks up where it stopped.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

require_login

# Uninstalling first lets Kubernetes release what it made in AWS: the ALB.
if [[ -n $(cluster_arn) ]] && kube get ns >/dev/null 2>&1; then
  for release in mycel mycel-stores; do
    helm --kube-context "$CONTEXT" uninstall "$release" --wait >/dev/null 2>&1 \
      && log "$release uninstalled" || true
  done
fi
# The controller deletes the ALB once the Ingress is gone; it must still be running then.
dns_unpoint_and_wait
helm --kube-context "$CONTEXT" uninstall aws-load-balancer-controller -n kube-system >/dev/null 2>&1 || true

log "terraform destroy (~8 min)"
tf_init
[[ -f "$SESSION_DIR/terraform.tfvars" ]] || echo 'owner_cidr = "0.0.0.0/32"' > "$SESSION_DIR/terraform.tfvars"
terraform -chdir="$SESSION_DIR" destroy -input=false -auto-approve >/dev/null
kubectl config delete-context "$CONTEXT" >/dev/null 2>&1 || true

"$(dirname "${BASH_SOURCE[0]}")/leftovers.sh"
