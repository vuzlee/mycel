#!/bin/sh
# Split the comma lists from .env into the numbered variables config.yaml names, then
# start the gateway. One list per provider in .env, however many keys it holds.
set -eu
i=1
for key in $(echo "${GEMINI_API_KEYS:-}" | tr ',' ' '); do export "GEMINI_API_KEY_$i=$key"; i=$((i + 1)); done
i=1
for key in $(echo "${CLAUDE_API_KEYS:-}" | tr ',' ' '); do export "CLAUDE_API_KEY_$i=$key"; i=$((i + 1)); done
exec litellm --config /app/config.yaml --port 4000 "$@"
