"""mycel_app: the role the running app connects as, able to change rows and nothing else

Revision ID: 0018
Revises: 0017

The app connected as the database owner, so a bug or an injection in it could drop any
table. Migrations need the owner; the app does not. This creates `mycel_app` with read and
write on every table and sequence, no DDL, membership of `mycel_reader` so `run_sql` can
still step down, and a gold read policy so the dashboard and sync are not hidden by the row
security that binds `mycel_reader`.

Runs as the owner (`MIGRATION_DATABASE_URL`), which is why it can be a migration rather than
a hand-run script: there is no step to forget. Unset `MYCEL_APP_PASSWORD` and it does
nothing, leaving a dev machine on the owner. The earlier three-role design (`grants.sql`,
`mycel_etl`) never had code that connected as `mycel_etl`, and is removed.

`downgrade` drops only the gold policies. The role `mycel_app` and its grants stay;
drop them by hand if the app should connect as the owner again.
"""

import os
from collections.abc import Sequence

from alembic import op

from mycel.core.config import get_settings

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP = "mycel_app"
SCHEMAS = ("bronze", "silver", "gold", "app")


def _password() -> str | None:
    """Through Settings, so `.env` counts: scripts run alembic without exporting it."""
    secret = get_settings().mycel_app_password
    return secret.get_secret_value() if secret else os.environ.get("MYCEL_APP_PASSWORD")


def upgrade() -> None:
    password = _password()
    if not password:
        return
    quoted = password.replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP}') THEN
                CREATE ROLE {APP} LOGIN;
            END IF;
        END
        $$
        """
    )
    op.execute(f"ALTER ROLE {APP} PASSWORD '{quoted}'")
    op.execute(f"GRANT CONNECT ON DATABASE {op.get_bind().engine.url.database} TO {APP}")
    for schema in SCHEMAS:
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {APP}")
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO {APP}"
        )
        op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {APP}")
        # Tables a later migration adds, created by the owner, are reachable too.
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP}"
        )
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT USAGE, SELECT ON SEQUENCES TO {APP}"
        )
    # `run_sql` steps down into the reader for one query; SET ROLE needs membership.
    op.execute(f"GRANT mycel_reader TO {APP}")
    # Row security binds mycel_reader; the app role is not the owner, so without these it
    # would read gold as empty. Every other reader checks permission a layer up.
    for table in ("work_item", "worklog"):
        op.execute(f"DROP POLICY IF EXISTS {table}_app_reads_all ON gold.{table}")
        op.execute(
            f"CREATE POLICY {table}_app_reads_all ON gold.{table} FOR ALL TO {APP} "
            "USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    for table in ("work_item", "worklog"):
        op.execute(f"DROP POLICY IF EXISTS {table}_app_reads_all ON gold.{table}")
