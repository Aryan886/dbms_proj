-- Backfilled backtest trades (spec story 48) live in the cloud's trade history
-- next to the rows that mirror SQLite. They are told apart by sign: SQLite ids
-- are positive, a backfilled row has a negative id and source = 'backtest'.
-- The sync and the bulk load only ever write positive ids.

ALTER TABLE dashboard_trade_history
    ADD CONSTRAINT dashboard_trade_history_backfill_tag CHECK (id > 0 OR source = 'backtest');

-- The bot sees exactly its own SQLite rows: backfilled trades stay out of compat.
CREATE OR REPLACE VIEW compat.dashboard_trade_history AS
SELECT t.id, t.strategy_id,
       COALESCE(oc.tradingsymbol, i.symbol)     AS symbol,
       (t.entry_ts AT TIME ZONE 'Asia/Kolkata') AS entry_ts,
       (t.exit_ts AT TIME ZONE 'Asia/Kolkata')  AS exit_ts,
       t.side, t.qty,
       t.entry_price::float8                    AS entry_price,
       t.exit_price::float8                     AS exit_price,
       t.realized_pnl::float8                   AS realized_pnl,
       t.status, t.source, t.position_type, t.section, t.subcat, t.exit_reason,
       t.sl_initial::float8                     AS sl_initial,
       t.sl_final::float8                       AS sl_final,
       t.sl_adjustments
FROM public.dashboard_trade_history t
JOIN public.instruments i ON i.id = t.instrument_id
LEFT JOIN public.option_contracts oc ON oc.id = t.contract_id
WHERE t.id > 0;
