-- 0004: header/line split for option-chain snapshots (strict 3NF).
--
-- FD found in the data: (instrument, ts) -> spot_price holds for every
-- option_data snapshot (160/160): the bot writes one spot per chain fetch.
-- Keeping spot_price on each line made it transitively dependent on the key
-- (contract, ts) -> (instrument, ts) -> spot_price. The spot (and the
-- snapshot time) move to a header table; each line references its header.
-- delta_cache is NOT split: there (symbol, ts) -> spot_price fails for 65 of
-- 13,676 timestamps, so spot is a genuine per-row attribute.

CREATE TABLE option_chain_snapshots (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_id  smallint NOT NULL REFERENCES instruments(id),
    ts             timestamptz NOT NULL,
    spot_price     numeric(12,2) NOT NULL CHECK (spot_price > 0),
    CONSTRAINT option_chain_snapshots_natural_key UNIQUE (instrument_id, ts)
);

-- Backfill headers from rows already loaded. Fails (and rolls back) if the FD
-- is violated in existing data, rather than silently picking one spot.
INSERT INTO option_chain_snapshots (instrument_id, ts, spot_price)
SELECT DISTINCT oc.instrument_id, os.ts, os.spot_price
FROM option_snapshots os JOIN option_contracts oc ON oc.id = os.contract_id;

ALTER TABLE option_snapshots ADD COLUMN chain_snapshot_id bigint REFERENCES option_chain_snapshots(id);
UPDATE option_snapshots os
SET chain_snapshot_id = h.id
FROM option_contracts oc, option_chain_snapshots h
WHERE oc.id = os.contract_id AND h.instrument_id = oc.instrument_id AND h.ts = os.ts;

ALTER TABLE option_snapshots
    ALTER COLUMN chain_snapshot_id SET NOT NULL,
    DROP CONSTRAINT option_snapshots_pkey,
    DROP COLUMN ts,
    DROP COLUMN spot_price,
    ADD PRIMARY KEY (chain_snapshot_id, contract_id);

-- Apply one option_data source row: contract + header + line. The FD is
-- enforced here: a row whose spot contradicts its snapshot's spot is rejected
-- (unless it is the snapshot's only line, i.e. a correction of that row).
CREATE FUNCTION apply_option_data(p_id bigint, p_ts text, p_symbol text, p_strike integer, p_type text,
                                  p_ltp double precision, p_iv double precision, p_expiry text,
                                  p_spot numeric, p_tradingsymbol text, p_oi bigint) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_contract integer;
    v_inst     smallint;
    v_ts       timestamptz := p_ts::timestamptz;
    v_spot     numeric(12,2) := round(p_spot, 2);
    v_chain    bigint;
    v_existing numeric(12,2);
BEGIN
    v_contract := upsert_observed_contract(p_symbol, p_expiry::date, p_strike, p_type, p_tradingsymbol);
    SELECT instrument_id INTO v_inst FROM option_contracts WHERE id = v_contract;

    INSERT INTO option_chain_snapshots (instrument_id, ts, spot_price)
    VALUES (v_inst, v_ts, v_spot)
    ON CONFLICT (instrument_id, ts) DO NOTHING;
    SELECT id, spot_price INTO v_chain, v_existing
    FROM option_chain_snapshots WHERE instrument_id = v_inst AND ts = v_ts;

    IF v_existing IS DISTINCT FROM v_spot THEN
        IF EXISTS (SELECT 1 FROM option_snapshots WHERE chain_snapshot_id = v_chain AND source_id <> p_id) THEN
            RAISE EXCEPTION 'spot_price % contradicts snapshot spot % at %', v_spot, v_existing, v_ts
                USING ERRCODE = 'check_violation', CONSTRAINT = 'option_chain_snapshots_spot_fd';
        END IF;
        UPDATE option_chain_snapshots SET spot_price = v_spot WHERE id = v_chain;
    END IF;

    INSERT INTO option_snapshots (chain_snapshot_id, contract_id, source_id, ltp, iv, open_interest)
    VALUES (v_chain, v_contract, p_id, p_ltp, p_iv, p_oi)
    ON CONFLICT (chain_snapshot_id, contract_id) DO UPDATE SET
        source_id = EXCLUDED.source_id, ltp = EXCLUDED.ltp, iv = EXCLUDED.iv,
        open_interest = EXCLUDED.open_interest;
END $$;
