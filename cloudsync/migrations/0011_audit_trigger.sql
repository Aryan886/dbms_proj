-- Audit trail for trading records (spec story 44): who changed what and when,
-- with the old and new rows as JSON.
--
-- The log lives in its own schema so no grant on `public` can ever reach it.
-- The trigger function runs with the caller's rights (not SECURITY DEFINER),
-- so `actor` is the role that really made the change (`sync_writer` for the
-- pipeline). That role may INSERT into the log, and nothing else: it can't
-- read, rewrite or delete the trail it leaves.

CREATE SCHEMA audit;

CREATE TABLE audit.audit_log (
    audit_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name  text NOT NULL,
    op          text NOT NULL CHECK (op IN ('INSERT', 'UPDATE', 'DELETE')),
    actor       text NOT NULL DEFAULT current_user,   -- effective role
    login       text NOT NULL DEFAULT session_user,   -- the login behind it
    changed_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    txid        bigint NOT NULL DEFAULT txid_current(),
    old_row     jsonb,
    new_row     jsonb,
    CHECK ((op = 'INSERT') = (old_row IS NULL) AND (op = 'DELETE') = (new_row IS NULL))
);
CREATE INDEX audit_log_table_changed_at ON audit.audit_log (table_name, changed_at);

CREATE FUNCTION audit.log_row_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO audit.audit_log (table_name, op, old_row, new_row)
    VALUES (TG_TABLE_NAME, TG_OP,
            CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END,
            CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END);
    RETURN NULL;
END $$;

-- The sync re-applies rows as upserts; an UPDATE that changes nothing is not a change.
CREATE TRIGGER audit_insert AFTER INSERT ON dashboard_trade_history
    FOR EACH ROW EXECUTE FUNCTION audit.log_row_change();
CREATE TRIGGER audit_update AFTER UPDATE ON dashboard_trade_history
    FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION audit.log_row_change();
CREATE TRIGGER audit_delete AFTER DELETE ON dashboard_trade_history
    FOR EACH ROW EXECUTE FUNCTION audit.log_row_change();

CREATE TRIGGER audit_insert AFTER INSERT ON dashboard_strategy_state
    FOR EACH ROW EXECUTE FUNCTION audit.log_row_change();
CREATE TRIGGER audit_update AFTER UPDATE ON dashboard_strategy_state
    FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION audit.log_row_change();
CREATE TRIGGER audit_delete AFTER DELETE ON dashboard_strategy_state
    FOR EACH ROW EXECUTE FUNCTION audit.log_row_change();

GRANT USAGE ON SCHEMA audit TO sync_writer;
GRANT INSERT ON audit.audit_log TO sync_writer;
