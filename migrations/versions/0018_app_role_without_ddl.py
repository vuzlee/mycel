"""mycel_app: the role the running app connects as, able to change rows and nothing else

Revision ID: 0018
Revises: 0017
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
    """Read through Settings so `.env` counts."""
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
    # Row security binds mycel_reader; without these the app role reads gold as empty.
    for table in ("work_item", "worklog"):
        op.execute(f"DROP POLICY IF EXISTS {table}_app_reads_all ON gold.{table}")
        op.execute(
            f"CREATE POLICY {table}_app_reads_all ON gold.{table} FOR ALL TO {APP} "
            "USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    for table in ("work_item", "worklog"):
        op.execute(f"DROP POLICY IF EXISTS {table}_app_reads_all ON gold.{table}")
