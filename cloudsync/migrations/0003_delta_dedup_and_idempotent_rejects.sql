-- 0003: deterministic delta_cache duplicate resolution + idempotent quarantine.

-- A source row is quarantined at most once; replaying a batch (crash
-- recovery) refreshes the entry instead of double-counting it.
CREATE UNIQUE INDEX rejected_rows_source_key ON rejected_rows (source_table, source_pk);

-- Upsert the contract an option_data / delta_cache row refers to; return its id.
-- Keyed on the natural key. An existing tradingsymbol is kept; an observed
-- expiry upgrades a contract previously derived from a trade symbol.
CREATE FUNCTION upsert_observed_contract(p_symbol text, p_expiry date, p_strike integer,
                                         p_type text, p_tradingsymbol text) RETURNS integer
LANGUAGE sql AS $$
    INSERT INTO option_contracts (instrument_id, expiry_date, strike, option_type, tradingsymbol, expiry_source)
    VALUES ((SELECT id FROM instruments WHERE symbol = p_symbol), p_expiry, p_strike, p_type,
            NULLIF(p_tradingsymbol, 'N/A'), 'observed')
    ON CONFLICT (instrument_id, expiry_date, strike, option_type) DO UPDATE SET
        tradingsymbol = COALESCE(option_contracts.tradingsymbol, EXCLUDED.tradingsymbol),
        expiry_source = 'observed'
    RETURNING id
$$;

-- Apply one delta_cache source row. Natural key is (contract, ts); when two
-- source rows share it, the HIGHEST source id is kept and the other goes to
-- rejected_rows, whichever order they arrive in. Same rule for bulk load
-- and continuous sync. Re-applying the surviving row is a plain update.
CREATE FUNCTION apply_delta_cache(p_id bigint, p_ts text, p_symbol text, p_expiry text, p_strike integer,
                                  p_type text, p_tradingsymbol text, p_delta double precision,
                                  p_spot numeric, p_ltp double precision) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_contract integer;
    v_ts       timestamptz := p_ts::timestamptz;
    v_prev     delta_snapshots%ROWTYPE;
BEGIN
    v_contract := upsert_observed_contract(p_symbol, p_expiry::date, p_strike, p_type, p_tradingsymbol);

    SELECT * INTO v_prev FROM delta_snapshots WHERE contract_id = v_contract AND ts = v_ts FOR UPDATE;

    IF NOT FOUND OR v_prev.source_id = p_id THEN
        INSERT INTO delta_snapshots (contract_id, ts, source_id, delta, spot_price, ltp)
        VALUES (v_contract, v_ts, p_id, p_delta, p_spot, p_ltp)
        ON CONFLICT (contract_id, ts) DO UPDATE SET
            delta = EXCLUDED.delta, spot_price = EXCLUDED.spot_price, ltp = EXCLUDED.ltp;

    ELSIF p_id > v_prev.source_id THEN
        -- Incoming row wins: quarantine the current survivor, then replace it.
        INSERT INTO rejected_rows (source_table, source_pk, raw_row, violated_constraint, detail)
        SELECT 'delta_cache', v_prev.source_id::text,
               jsonb_build_object('id', v_prev.source_id, 'timestamp', p_ts, 'strike_price', oc.strike,
                                  'option_type', oc.option_type, 'delta', v_prev.delta,
                                  'expiry_date', oc.expiry_date, 'spot_price', v_prev.spot_price,
                                  'symbol', p_symbol, 'ltp', v_prev.ltp, 'tradingsymbol', oc.tradingsymbol),
               'delta_snapshots_pkey',
               format('duplicate (contract, ts); superseded by higher source id %s', p_id)
        FROM option_contracts oc WHERE oc.id = v_contract
        ON CONFLICT (source_table, source_pk) DO UPDATE SET
            detail = EXCLUDED.detail, rejected_at = now();

        UPDATE delta_snapshots
        SET source_id = p_id, delta = p_delta, spot_price = p_spot, ltp = p_ltp
        WHERE contract_id = v_contract AND ts = v_ts;

    ELSE
        -- Incoming row loses to an already-stored higher source id.
        INSERT INTO rejected_rows (source_table, source_pk, raw_row, violated_constraint, detail)
        VALUES ('delta_cache', p_id::text,
                jsonb_build_object('id', p_id, 'timestamp', p_ts, 'strike_price', p_strike,
                                   'option_type', p_type, 'delta', p_delta, 'expiry_date', p_expiry,
                                   'spot_price', p_spot, 'symbol', p_symbol, 'ltp', p_ltp,
                                   'tradingsymbol', p_tradingsymbol),
                'delta_snapshots_pkey',
                format('duplicate (contract, ts); kept higher source id %s', v_prev.source_id))
        ON CONFLICT (source_table, source_pk) DO UPDATE SET
            detail = EXCLUDED.detail, rejected_at = now();
    END IF;
END $$;
