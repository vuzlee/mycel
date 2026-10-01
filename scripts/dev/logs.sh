#!/usr/bin/env bash
#
# Follow one host process: api, worker or scheduler.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

name=${1:-}
[[ -n $name ]] || die "which process: api, worker or scheduler"
[[ -f "$RUN/$name.log" ]] || die "no log for $name — is it running? scripts/stack.sh dev status"
exec tail -f "$RUN/$name.log"
