#!/usr/bin/env bash
#
# The two least-privilege roles, from migrations/grants.sql.
#
# Separate from any `up` because it needs a superuser and because it is not idempotent in
# the way `up` is — it revokes, and a deployment decides when to.
#
# Passwords come from the environment so they stay out of the shell history.

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

app_pw=${MYCEL_APP_PASSWORD:-}
etl_pw=${MYCEL_ETL_PASSWORD:-}
[[ -n $app_pw && -n $etl_pw ]] || die "set MYCEL_APP_PASSWORD and MYCEL_ETL_PASSWORD first"

pg=$(cid postgres)
[[ -n $pg ]] || die "postgres is not running — scripts/stack.sh dev up"
wait_for postgres "docker exec $pg pg_isready -U mycel"

# `GRANT ... ON ALL TABLES` only reaches tables that exist, and `ALTER DEFAULT PRIVILEGES`
# covers the ones a later migration adds — so the migrations go first.
log "applying migrations first — grants only reach tables that exist"
uv run alembic upgrade head

docker cp "$ROOT/migrations/grants.sql" "$pg:/tmp/grants.sql" >/dev/null
docker exec "$pg" psql -U mycel -d mycel \
  -v app_password="$app_pw" -v etl_password="$etl_pw" -f /tmp/grants.sql
docker exec "$pg" rm -f /tmp/grants.sql
log "mycel_app reads gold and owns app; mycel_etl writes bronze, silver and gold"
