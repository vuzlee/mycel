#!/usr/bin/env bash
#
# Rebuild the dev broker on a fresh data directory, keeping users and permissions.
#
#   scripts/stack.sh broker-rebuild
#
# For what cannot change in place: a queue's arguments, and the node name (4.x with Khepri
# cannot rename a node). Refuses unless every queue is empty. The app redeclares its own
# topology on first use.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

require_env
rmq() { docker exec "$(cid rabbitmq)" rabbitmqctl "$@"; }

busy=$(rmq list_queues -q name messages | awk 'NR>1 && $2!=0')
[[ -z $busy ]] || die "queues are not empty, nothing was changed:
$busy"

defs=$(mktemp --suffix=.json)
rmq export_definitions /tmp/defs.json >/dev/null
docker cp "$(cid rabbitmq):/tmp/defs.json" "$defs"
log "definitions saved to $defs"

backup="rabbitdata-$(date +%Y%m%d-%H%M%S).tgz"
docker compose stop rabbitmq
docker run --rm -v mycel-rabbitdata:/d -v /tmp:/b alpine \
  sh -c "tar czf /b/$backup -C /d . && find /d -mindepth 1 -delete && chown 100:101 /d &&
         head -c 32 /dev/urandom | base64 | tr -dc A-Za-z | head -c 20 > /d/.erlang.cookie &&
         chown 100:101 /d/.erlang.cookie && chmod 400 /d/.erlang.cookie"
# The image's own cookie lands root-owned on an empty volume and the node cannot read it,
# so the wipe leaves one owned by rabbitmq (uid 100).
log "old data backed up to /tmp/$backup, volume emptied"

docker compose up -d --force-recreate rabbitmq
wait_for rabbitmq "docker exec $(cid rabbitmq) rabbitmq-diagnostics -q check_port_connectivity" 90
rmq enable_feature_flag all >/dev/null

# Only who may connect; queues and exchanges come back from the app's own declaration.
python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
json.dump({k: d[k] for k in ('users', 'vhosts', 'permissions')}, open(sys.argv[1], 'w'))
" "$defs"
docker cp "$defs" "$(cid rabbitmq):/tmp/defs.json"
rmq import_definitions /tmp/defs.json >/dev/null
rm -f "$defs"
log "users and permissions restored; node: $(rmq eval 'node().' 2>/dev/null)"
