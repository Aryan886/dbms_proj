-- 0005: continuous-sync bookkeeping, delete mapping, and contract correction.

-- ---------- sync bookkeeping ----------
-- Per source table: the highest SQLite _changelog seq whose effect is committed
-- here. Moved in the SAME transaction as the batch's upserts/deletes, which is
-- what makes a replay after a crash harmless (exactly-once effect).
CREATE TABLE sync_state (
    source_table  text PRIMARY KEY,
    last_seq      bigint NOT NULL CHECK (last_seq >= 0),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- One row per committed batch (monitoring / sync-lag view on day 4).
CREATE TABLE sync_batches (
    batch_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    first_seq     bigint NOT NULL,
    last_seq      bigint NOT NULL,
    entries       integer NOT NULL,
    upserts       integer NOT NULL,
    deletes       integer NOT NULL,
    rejected      integer NOT NULL,
    tables        text[] NOT NULL,
    started_at    timestamptz NOT NULL,
    committed_at  timestamptz NOT NULL,
    latency_ms    double precision NOT NULL,  -- batch start -> commit
    max_lag_ms    double precision,           -- oldest change captured in SQLite -> commit
    CHECK (last_seq >= first_seq)
);

-- Column-list fingerprint of each SQLite source table, taken at CDC install.
-- A live list that no longer matches pauses that table only.
CREATE TABLE schema_fingerprints (
    source_table       text PRIMARY KEY,
    columns            jsonb NOT NULL,
    fingerprint        text NOT NULL,
    status             text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    paused_at_version  integer,   -- schema_version when paused; resuming needs a newer one
    live_columns       jsonb,
    live_fingerprint   text,
    detected_at        timestamptz,
    updated_at         timestamptz NOT NULL DEFAULT now()
);

-- ---------- delete mapping ----------
-- option_data row deleted at the source: drop its line, and its chain header
-- once no line references it.
CREATE FUNCTION delete_option_data(p_id bigint) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_chain bigint;
BEGIN
    DELETE FROM option_snapshots WHERE source_id = p_id RETURNING chain_snapshot_id INTO v_chain;
    IF FOUND THEN
        DELETE FROM option_chain_snapshots h
        WHERE h.id = v_chain AND NOT EXISTS (SELECT 1 FROM option_snapshots s WHERE s.chain_snapshot_id = v_chain);
    END IF;
END $$;

-- delta_cache row deleted at the source. If it was the surviving row of a
-- duplicate group, the highest quarantined sibling is promoted, so the
-- "highest remaining source id wins" rule keeps holding after deletes.
CREATE FUNCTION delete_delta_cache(p_id bigint) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_gone  delta_snapshots%ROWTYPE;
    v_oc    option_contracts%ROWTYPE;
    v_sym   text;
    v_next  rejected_rows%ROWTYPE;
BEGIN
    DELETE FROM delta_snapshots WHERE source_id = p_id RETURNING * INTO v_gone;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT * INTO v_oc FROM option_contracts WHERE id = v_gone.contract_id;
    SELECT symbol INTO v_sym FROM instruments WHERE id = v_oc.instrument_id;

    SELECT r.* INTO v_next FROM rejected_rows r
    WHERE r.source_table = 'delta_cache' AND r.violated_constraint = 'delta_snapshots_pkey'
      AND (r.raw_row->>'timestamp')::timestamptz = v_gone.ts
      AND (r.raw_row->>'strike_price')::integer = v_oc.strike
      AND r.raw_row->>'option_type' = v_oc.option_type
      AND (r.raw_row->>'expiry_date')::date = v_oc.expiry_date
      AND r.raw_row->>'symbol' = v_sym
    ORDER BY r.source_pk::bigint DESC
    LIMIT 1;
    IF FOUND THEN
        DELETE FROM rejected_rows WHERE id = v_next.id;
        PERFORM apply_delta_cache(v_next.source_pk::bigint, v_next.raw_row->>'timestamp', v_sym,
                                  v_next.raw_row->>'expiry_date', v_oc.strike, v_oc.option_type,
                                  v_next.raw_row->>'tradingsymbol', (v_next.raw_row->>'delta')::float8,
                                  (v_next.raw_row->>'spot_price')::numeric, (v_next.raw_row->>'ltp')::float8);
    END IF;
END $$;

-- ---------- contract correction (day-1 open item) ----------
-- A trade can arrive before any option row for its contract (CDC order). The
-- trade's contract is then 'derived', possibly with a guessed expiry (monthly
-- symbols carry no expiry day; exchange holidays move it). When an observed
-- row arrives the observation wins:
--   * a derived contract holding the same tradingsymbol under a different
--     natural key is corrected to the observed key (or merged into an existing
--     contract with that key, its trades re-pointed);
--   * on the same natural key, an observed tradingsymbol replaces a derived one.
CREATE OR REPLACE FUNCTION upsert_observed_contract(p_symbol text, p_expiry date, p_strike integer,
                                                    p_type text, p_tradingsymbol text) RETURNS integer
LANGUAGE plpgsql AS $$
#variable_conflict use_column
DECLARE
    v_inst     smallint := (SELECT id FROM instruments WHERE symbol = p_symbol);
    v_tsym     text := NULLIF(p_tradingsymbol, 'N/A');
    v_derived  integer;
    v_target   integer;
    v_id       integer;
BEGIN
    IF v_tsym IS NOT NULL THEN
        SELECT id INTO v_derived FROM option_contracts
        WHERE tradingsymbol = v_tsym AND expiry_source = 'derived'
          AND (instrument_id, expiry_date, strike, option_type) IS DISTINCT FROM (v_inst, p_expiry, p_strike, p_type);
        IF FOUND THEN
            SELECT id INTO v_target FROM option_contracts
            WHERE instrument_id = v_inst AND expiry_date = p_expiry AND strike = p_strike AND option_type = p_type;
            IF FOUND THEN
                UPDATE dashboard_trade_history SET contract_id = v_target WHERE contract_id = v_derived;
                DELETE FROM option_contracts WHERE id = v_derived;
            ELSE
                UPDATE option_contracts
                SET instrument_id = v_inst, expiry_date = p_expiry, strike = p_strike, option_type = p_type,
                    expiry_source = 'observed'
                WHERE id = v_derived;
            END IF;
        END IF;
    END IF;

    INSERT INTO option_contracts AS oc (instrument_id, expiry_date, strike, option_type, tradingsymbol, expiry_source)
    VALUES (v_inst, p_expiry, p_strike, p_type, v_tsym, 'observed')
    ON CONFLICT (instrument_id, expiry_date, strike, option_type) DO UPDATE SET
        tradingsymbol = CASE WHEN oc.expiry_source = 'derived'
                             THEN COALESCE(EXCLUDED.tradingsymbol, oc.tradingsymbol)
                             ELSE COALESCE(oc.tradingsymbol, EXCLUDED.tradingsymbol) END,
        expiry_source = 'observed'
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;
