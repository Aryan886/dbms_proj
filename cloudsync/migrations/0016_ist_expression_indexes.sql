-- Index audit outcome (spec story 40; measured in artifacts/day4/index_audit/).
--
-- The compat views expose ts AT TIME ZONE 'Asia/Kolkata', so the bot's
-- predicates and ORDER BY are on that expression, which the primary keys on
-- (…, ts) can't serve. timezone(text, timestamptz) is IMMUTABLE, so it can be
-- indexed. Measured on the main data (median of 5 EXPLAIN ANALYZE runs):
--   latest 200 1m candles      12.3 ms -> 1.7 ms   (BRIN on the same expression: 5.8 ms)
--   latest delta snapshot rows 175.9 ms -> 0.13 ms (BRIN: 3.2 ms)
-- B-tree wins on these top-N / point lookups; BRIN is ~50x smaller but needs
-- a bitmap heap scan of whole block ranges, and candles.ts is only 0.55
-- correlated with physical order (four timeframes interleaved).
-- No variant helped the full-range backtest read (it returns every row) or
-- the MAX(timestamp) shapes (they aggregate through the view's joins).

CREATE INDEX candles_ist_ts ON candles (instrument_id, timeframe, (ts AT TIME ZONE 'Asia/Kolkata'));
CREATE INDEX delta_snapshots_ist_ts ON delta_snapshots ((ts AT TIME ZONE 'Asia/Kolkata'));
