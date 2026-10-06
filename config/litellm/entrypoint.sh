#!/bin/sh
# Split comma lists from .env into numbered variables (GEMINI_API_KEYS -> GEMINI_API_KEY_1,
# _2, ...), merge the deployment's models.yaml into config.yaml, then start the gateway.
# Any variable whose name ends in _API_KEYS is split the same way, so a new provider
# needs no change here.
set -eu
for list in $(env | sed -n 's/^\([A-Z0-9_]*_API_KEYS\)=.*/\1/p'); do
  base=${list%S}
  i=1
  for key in $(printenv "$list" | tr ',' ' '); do export "${base}_$i=$key"; i=$((i + 1)); done
done
[ -f /app/models.yaml ] || { echo "config/litellm/models.yaml is missing — copy models.example.yaml" >&2; exit 1; }
python - <<'PY'
import yaml
base = yaml.safe_load(open("/app/config.yaml")) or {}
base["model_list"] = (yaml.safe_load(open("/app/models.yaml")) or {}).get("model_list", [])
yaml.safe_dump(base, open("/tmp/litellm.yaml", "w"), sort_keys=False)
PY
exec litellm --config /tmp/litellm.yaml --port 4000 "$@"
