-- 0006: compatibility views (spec story 14).
--
-- The schema `compat` holds one view per in-scope SQLite table, with the SAME
-- name and the SAME column names and order (surrogate ids included). A client
-- whose search_path is `compat` (the bot_reader role, day 4) can run the bot's
-- queries unchanged. A separate schema is needed because some base tables
-- already carry a source table's name (signals, dashboard_*).
--
-- Types are what the bot's code expects back from SQLite: wall-clock
-- timestamps in Asia/Kolkata (timestamp without time zone, independent of the
-- session time zone) and prices as double precision (SQLite REAL).
--
-- Column order follows PRODUCTION, not the bot's create_tables(): in the real
-- database market_data_1m/5m/15m end in SL, SH, vix_value (added later by
-- ALTER TABLE), while market_data_1h ends in vix_value, SL, SH.
CREATE SCHEMA compat;

-- One shared join of candles + their stored indicators; each timeframe's
-- view only picks its rows and its production column order.
CREATE VIEW compat._candle_rows AS
SELECT c.timeframe,
       c.source_id                                AS id,
       (c.ts AT TIME ZONE 'Asia/Kolkata')         AS "timestamp",
       i.symbol                                   AS symbol,
       c.open::float8                             AS open,
       c.high::float8                             AS high,
       c.low::float8                              AS low,
       c.close::float8                            AS close,
       ci.ao_value, ci.donchian_upper, ci.donchian_lower, ci.donchian_mid,
       ci.sl, ci.sh, ci.vix_value
FROM public.candles c
JOIN public.instruments i ON i.id = c.instrument_id
LEFT JOIN public.candle_indicators ci
       ON (ci.instrument_id, ci.timeframe, ci.ts) = (c.instrument_id, c.timeframe, c.ts);

CREATE VIEW compat.market_data_1m AS
SELECT id, "timestamp", symbol, open, high, low, close, ao_value, donchian_upper, donchian_lower,
       donchian_mid, sl AS "SL", sh AS "SH", vix_value
FROM compat._candle_rows WHERE timeframe = '1m';

CREATE VIEW compat.market_data_5m AS
SELECT id, "timestamp", symbol, open, high, low, close, ao_value, donchian_upper, donchian_lower,
       donchian_mid, sl AS "SL", sh AS "SH", vix_value
FROM compat._candle_rows WHERE timeframe = '5m';

CREATE VIEW compat.market_data_15m AS
SELECT id, "timestamp", symbol, open, high, low, close, ao_value, donchian_upper, donchian_lower,
       donchian_mid, sl AS "SL", sh AS "SH", vix_value
FROM compat._candle_rows WHERE timeframe = '15m';

CREATE VIEW compat.market_data_1h AS
SELECT id, "timestamp", symbol, open, high, low, close, ao_value, donchian_upper, donchian_lower,
       donchian_mid, vix_value, sl AS "SL", sh AS "SH"
FROM compat._candle_rows WHERE timeframe = '1h';

CREATE VIEW compat.vix_data AS
SELECT (v.ts AT TIME ZONE 'Asia/Kolkata') AS "timestamp",
       i.symbol                           AS symbol,
       v.value                            AS vix_value,
       v.ao_value                         AS vix_ao_value,
       v.donchian_upper                   AS vix_donchian_upper,
       v.donchian_lower                   AS vix_donchian_lower,
       v.donchian_mid                     AS vix_donchian_mid
FROM public.vix_observations v
LEFT JOIN public.instruments i ON i.id = v.instrument_id;

CREATE VIEW compat.signals AS
SELECT s.id,
       (s.ts AT TIME ZONE 'Asia/Kolkata') AS "timestamp",
       i.symbol                           AS symbol,
       s.signal, s.reason, s.confidence_score
FROM public.signals s
JOIN public.instruments i ON i.id = s.instrument_id;

CREATE VIEW compat.dashboard_strategy_state AS
SELECT strategy_id, display_name, status, mode,
       (last_started_at AT TIME ZONE 'Asia/Kolkata') AS last_started_at,
       (last_stopped_at AT TIME ZONE 'Asia/Kolkata') AS last_stopped_at,
       (updated_at AT TIME ZONE 'Asia/Kolkata')      AS updated_at
FROM public.dashboard_strategy_state;

-- The source `symbol` is the option's tradingsymbol when the trade resolved to
-- a contract (migration 0002), otherwise the instrument's symbol.
CREATE VIEW compat.dashboard_trade_history AS
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
LEFT JOIN public.option_contracts oc ON oc.id = t.contract_id;

-- option_data = chain header (time, spot) + line + contract master.
CREATE VIEW compat.option_data AS
SELECT s.source_id                        AS id,
       (h.ts AT TIME ZONE 'Asia/Kolkata') AS "timestamp",
       i.symbol                           AS symbol,
       oc.strike                          AS strike_price,
       oc.option_type::text               AS option_type,
       s.ltp, s.iv,
       oc.expiry_date,
       h.spot_price::float8               AS spot_price,
       oc.tradingsymbol,
       s.open_interest
FROM public.option_snapshots s
JOIN public.option_chain_snapshots h ON h.id = s.chain_snapshot_id
JOIN public.option_contracts oc ON oc.id = s.contract_id
JOIN public.instruments i ON i.id = oc.instrument_id;

-- delta_cache: the surviving row of each (contract, ts); quarantined
-- duplicates (rejected_rows) are not part of the cloud copy.
CREATE VIEW compat.delta_cache AS
SELECT d.source_id                        AS id,
       (d.ts AT TIME ZONE 'Asia/Kolkata') AS "timestamp",
       oc.strike                          AS strike_price,
       oc.option_type::text               AS option_type,
       d.delta,
       oc.expiry_date,
       d.spot_price::float8               AS spot_price,
       i.symbol                           AS symbol,
       d.ltp,
       oc.tradingsymbol
FROM public.delta_snapshots d
JOIN public.option_contracts oc ON oc.id = d.contract_id
JOIN public.instruments i ON i.id = oc.instrument_id;
