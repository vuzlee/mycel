#!/usr/bin/env bash
#
# One Jira sync now, without waiting for the scheduler's tick.
#
#   scripts/stack.sh sync              fetch what changed since the watermark
#   scripts/stack.sh sync --refetch    read the whole project again
#
# `--refetch` is for after a FIELD is added to the sync rather than after data changed:
# the watermark cannot see that the question is different, so an ordinary sync fetches
# nothing and the new column stays empty.
#
# Runs on the host against the host's .env in every mode, including k8s — this is a
# one-off read, and routing it through a pod would only add a way for it to fail.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

require_env

if [[ ${1:-} == "--refetch" ]]; then
  exec uv run python -c "
import asyncio
from mycel.domains.sync import refetch_jira
print(asyncio.run(refetch_jira()))"
fi

exec uv run python -c "
import asyncio
from mycel.domains.sync import sync_jira
print(asyncio.run(sync_jira()))"
