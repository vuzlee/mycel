#!/usr/bin/env bash
#
#   scripts/stack.sh aws extend <hours>   the cluster now expires that many hours from now

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[[ ${1:-} =~ ^[0-9]+$ ]] || die "usage: scripts/stack.sh aws extend <hours>"
(( $1 <= 12 )) || die "at most 12 h at a time"
require_login
[[ -n $(cluster_arn) ]] || die "no cluster $CLUSTER"
set_expiry "$1"
