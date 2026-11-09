-- Least-privilege roles (spec stories 42-43).
--
-- Roles are cluster-wide in Postgres, so they are created only if missing
-- (several databases on one server, e.g. the test databases, share them).
-- They are NOLOGIN group roles: no password lives in a migration. A consumer
-- connects as a login that is a member, or with `options=-c role=<name>`.
-- Grants are per database, so they are (re)applied here every time.

DO $$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['sync_writer', 'bot_reader', 'analyst'] LOOP
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', r);
        END IF;
    END LOOP;
END $$;

-- sync_writer: read/write on the base and bookkeeping tables in `public`, and
-- nothing else. `public` also holds views (indicators, data quality), so the
-- grant goes table by table rather than ON ALL TABLES. A later migration that
-- adds a base table calls this function again.
CREATE FUNCTION grant_sync_writer_base_tables() RETURNS void LANGUAGE plpgsql AS $$
DECLARE t regclass;
BEGIN
    FOR t IN SELECT c.oid::regclass FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') LOOP
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %s TO sync_writer', t);
    END LOOP;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sync_writer;
END $$;
SELECT grant_sync_writer_base_tables();

-- bot_reader: read access to the compatibility views only.
GRANT USAGE ON SCHEMA compat TO bot_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA compat TO bot_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA compat GRANT SELECT ON TABLES TO bot_reader;

-- analyst: read access to the analytics views only. They live in their own
-- schema; views run with their owner's rights, so the analyst needs no grant
-- on the base tables behind them.
CREATE SCHEMA analytics;
GRANT USAGE ON SCHEMA analytics TO analyst;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO analyst;
