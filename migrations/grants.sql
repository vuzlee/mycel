-- Per-schema privileges. Run by hand, by a superuser, after `alembic upgrade head`.
--
-- Not a migration. A migration runs as the application's own role, and a role cannot
-- meaningfully take privileges away from itself — it can grant them straight back. These
-- statements have to come from somewhere above the application, which is an operator.
--
-- The split follows the layer boundary the schemas already draw:
--
--   mycel_etl     writes bronze and silver, writes gold, reads nothing in app
--   mycel_app     reads gold, reads and writes app — never touches bronze or silver
--
-- Why it matters: `src/mycel/agents/` reads gold and nothing else, and a bug that reaches
-- past it currently fails as a code review rather than as a permission error. This makes
-- the database enforce what the import graph asks for.
--
--   psql "$DATABASE_URL" -v app_password=... -v etl_password=... -f migrations/grants.sql

\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mycel_app') THEN
        CREATE ROLE mycel_app LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mycel_etl') THEN
        CREATE ROLE mycel_etl LOGIN;
    END IF;
END
$$;

ALTER ROLE mycel_app PASSWORD :'app_password';
ALTER ROLE mycel_etl PASSWORD :'etl_password';

-- Nothing by default, then back only what each role is for. `REVOKE ... FROM PUBLIC` is
-- the part usually forgotten: without it every role can create tables in `public` and read
-- whatever the schema owner left open.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA bronze, silver, gold, app FROM PUBLIC;

GRANT USAGE ON SCHEMA bronze, silver, gold TO mycel_etl;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA bronze, silver, gold TO mycel_etl;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA bronze, silver, gold TO mycel_etl;

GRANT USAGE ON SCHEMA gold, app TO mycel_app;
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO mycel_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO mycel_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO mycel_app;

-- The same for tables a later migration adds. Without these two lines every `alembic
-- upgrade` leaves a new table readable by nobody, and the failure lands in production
-- rather than here.
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze, silver, gold
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mycel_etl;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO mycel_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA app
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mycel_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO mycel_app;

-- Batch 055 put gold behind row-level security so `run_sql` can be scoped to the asker's
-- granted projects. RLS is bypassed by a table's *owner* and by nobody else — and in a
-- deployment that ran this file, `mycel_app` is not the owner. Without the two statements
-- below it would read zero rows from gold, and `gather_progress`, the dashboard and the
-- board would all go empty with no error anywhere.
--
-- So `mycel_app` gets an unconditional read, and steps down into `mycel_reader` for the
-- length of one model-written query. The narrow role is the one with the policy; the
-- application role is deliberately unrestricted, because every other reader checks
-- permission a layer up in `services/permission.py`.
GRANT mycel_reader TO mycel_app;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['work_item', 'worklog'] LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON gold.%I', t || '_app_reads_all', t);
        EXECUTE format(
            'CREATE POLICY %I ON gold.%I FOR SELECT TO mycel_app USING (true)',
            t || '_app_reads_all', t
        );
    END LOOP;
END
$$;
