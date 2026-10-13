#!/usr/bin/env bash
#
# Parked jobs: count them, or put them back on their work queue.
#
#   scripts/stack.sh replay                 how many jobs sit in each dead-letter queue
#   scripts/stack.sh replay jobs.dlq [N]    move up to N (default 100) back, attempts reset
#
# Read why a job was parked first (`mycel-error` header, RabbitMQ UI :15672): a job that
# failed for a reason still true fails again.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

require_env

if [[ -z ${1:-} ]]; then
  exec uv run python -c "
import asyncio
from mycel.queue.replay import depths
print(asyncio.run(depths()))"
fi

exec uv run python -c "
import asyncio, sys
from mycel.queue.replay import replay
print(asyncio.run(replay(sys.argv[1], int(sys.argv[2]))), 'moved')" "$1" "${2:-100}"
