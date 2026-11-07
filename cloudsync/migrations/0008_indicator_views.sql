-- 0008: indicators computed in SQL with window functions (spec story 15).
--
-- Same definitions as the bot (core/indicators.py, utils/market_data_1h.py):
--   SMA_n      mean of the last n closes, EXPANDING until n rows exist
--              (the bot's compute_smas_with_high_low uses min_periods=1);
--   AO         SMA_5 - SMA_34 of the median price (high + low) / 2, full windows only;
--   Donchian   max(high) / min(low) over the last 20 candles, full windows only;
--              mid = (upper + lower) / 2.
-- "Full windows only" is a count(*) over the same frame: until the frame holds
-- n rows the value is NULL, like pandas' min_periods=n.
--
-- The stored values the bot wrote (candle_indicators, candle_sma) stay the
-- source of truth for parity; this view is the derived-attribute version and
-- feeds the drift check (0009).
CREATE VIEW candle_indicators_computed AS
WITH p AS (
    SELECT c.instrument_id, c.timeframe, c.ts,
           c.close::float8 AS close, c.high::float8 AS high, c.low::float8 AS low,
           (c.high::float8 + c.low::float8) / 2 AS median
    FROM candles c
), w AS (
    SELECT p.*,
           avg(close)  OVER w5   AS sma_5,
           avg(close)  OVER w20  AS sma_20,
           avg(close)  OVER w50  AS sma_50,
           avg(close)  OVER w200 AS sma_200,
           avg(high)   OVER w5   AS sma_5_high,
           avg(low)    OVER w5   AS sma_5_low,
           avg(median) OVER w5   AS median_5,
           avg(median) OVER w34  AS median_34,
           count(*)    OVER w5   AS n5,
           count(*)    OVER w34  AS n34,
           max(high)   OVER w20  AS high_20,
           min(low)    OVER w20  AS low_20,
           count(*)    OVER w20  AS n20
    FROM p
    WINDOW s    AS (PARTITION BY instrument_id, timeframe ORDER BY ts),
           w5   AS (s ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
           w20  AS (s ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
           w34  AS (s ROWS BETWEEN 33 PRECEDING AND CURRENT ROW),
           w50  AS (s ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
           w200 AS (s ROWS BETWEEN 199 PRECEDING AND CURRENT ROW)
)
SELECT w.instrument_id, i.symbol, w.timeframe, w.ts, w.close,
       w.sma_5, w.sma_20, w.sma_50, w.sma_200, w.sma_5_high, w.sma_5_low,
       CASE WHEN w.n34 = 34 THEN w.median_5 - w.median_34 END       AS ao_value,
       CASE WHEN w.n20 = 20 THEN w.high_20 END                      AS donchian_upper,
       CASE WHEN w.n20 = 20 THEN w.low_20 END                       AS donchian_lower,
       CASE WHEN w.n20 = 20 THEN (w.high_20 + w.low_20) / 2 END     AS donchian_mid
FROM w
JOIN instruments i ON i.id = w.instrument_id;
