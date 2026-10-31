#!/bin/sh
# Split each comma list of keys (FOO_API_KEY=a,b or FOO_API_KEYS=a,b) into numbered
# variables (FOO_API_KEY_1, _2) that models.yaml names, then start the gateway. Any provider
# works, so a new one needs no change here. models.yaml is pulled in by `include`.
set -eu
for list in $(env | sed -n 's/^\([A-Z0-9_]*_API_KEYS\{0,1\}\)=.*/\1/p'); do
  base=${list%S}
  i=1
  for key in $(printenv "$list" | tr ',' ' '); do export "${base}_$i=$key"; i=$((i + 1)); done
done
exec litellm --config /app/config.yaml --port 4000 "$@"
