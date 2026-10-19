#!/usr/bin/env bash
# The app's scoped key to the gateway, made with the master key. Prints it; paste it into
# .env as LITELLM_API_KEY. The master key stays with the gateway.
#
#   scripts/stack.sh gateway-key            # every host model, $10 a month
#   scripts/stack.sh gateway-key 200        # a different monthly cap, in USD

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

require_env
need curl
need jq

budget=${1:-10}
master=$(sed -n 's/^LITELLM_MASTER_KEY=//p' "$ROOT/.env")
[[ -n $master ]] || die "LITELLM_MASTER_KEY is not set in .env"
base=${LITELLM_BASE_URL:-http://localhost:4000}

docker compose exec -T postgres sh -c \
  'psql -U "${POSTGRES_USER:-mycel}" -tc "select 1 from pg_database where datname = '"'litellm'"'" | grep -q 1 \
   || psql -U "${POSTGRES_USER:-mycel}" -c "create database litellm"' >/dev/null

models=$(uv run python -c "
from mycel.core.config import get_settings
import json; print(json.dumps([m.name for m in get_settings().host_models]))")

curl -fsS "$base/key/generate" \
  -H "Authorization: Bearer $master" -H "Content-Type: application/json" \
  -d "{\"key_alias\": \"mycel-app\", \"models\": $models, \"max_budget\": $budget, \"budget_duration\": \"30d\"}" \
  | jq -r .key
