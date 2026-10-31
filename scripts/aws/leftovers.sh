#!/usr/bin/env bash
#
# Fails loudly when anything that costs money is still there after `down`.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

left=()
check() {
  local what=$1 found
  found=$(aws_ "${@:2}" --output text)
  [[ -z $found || $found == None ]] || left+=("$what: $found")
}

check "EKS clusters"   eks list-clusters --query 'clusters'
check "EC2 instances"  ec2 describe-instances --filters Name=tag-key,Values=mycel-session \
  Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId'
check "volumes"        ec2 describe-volumes --filters Name=tag-key,Values=mycel-session --query 'Volumes[].VolumeId'
check "ENIs"           ec2 describe-network-interfaces --filters Name=tag-key,Values=mycel-session --query 'NetworkInterfaces[].NetworkInterfaceId'
check "addresses"      ec2 describe-addresses --filters Name=tag-key,Values=mycel-session --query 'Addresses[].PublicIp'
check "load balancers" elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName'
check "VPCs"           ec2 describe-vpcs --filters Name=tag-key,Values=mycel-session --query 'Vpcs[].VpcId'
check "NAT gateways"   ec2 describe-nat-gateways --filter Name=state,Values=pending,available --query 'NatGateways[].NatGatewayId'

if (( ${#left[@]} )); then
  printf '\033[31mxx\033[0m still there, and some cost money:\n' >&2
  printf '   %s\n' "${left[@]}" >&2
  exit 1
fi
log "nothing left that costs money"
