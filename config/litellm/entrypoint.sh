#!/bin/sh
# Split each comma list in the environment (GEMINI_API_KEYS=a,b) into numbered variables
# (GEMINI_API_KEY_1, _2) that models.yaml names, then start the gateway. Any *_API_KEYS
# works, so a new provider needs no change here. models.yaml is pulled in by `include`.
set -eu
for list in $(env | sed -n 's/^\([A-Z0-9_]*_API_KEYS\)=.*/\1/p'); do
  i=1
  for key in $(printenv "$list" | tr ',' ' '); do export "${list%S}_$i=$key"; i=$((i + 1)); done
done
exec litellm --config /app/config.yaml --port 4000 "$@"
