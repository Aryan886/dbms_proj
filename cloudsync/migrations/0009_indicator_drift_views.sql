-- 0009: data-quality view of the drift between the indicator values the bot
-- STORED and the same indicators COMPUTED in SQL (spec story 17).
--
-- One row per (candle, indicator) that differs: a value on one side only, or
-- an absolute difference above 1e-6 (float summation order can differ in the
-- last bits). SL/SH are not compared: they come from a path-dependent
-- backfill with no window-function equivalent. A stored SMA row without a
-- candle shows up with computed = NULL.
CREATE VIEW dq_indicator_pairs AS
SELECT i.symbol, s.timeframe, s.ts, v.indicator, v.stored, v.computed
FROM candle_indicators s
JOIN instruments i ON i.id = s.instrument_id
LEFT JOIN candle_indicators_computed c USING (instrument_id, timeframe, ts)
CROSS JOIN LATERAL (VALUES
    ('ao_value',       s.ao_value,       c.ao_value),
    ('donchian_upper', s.donchian_upper, c.donchian_upper),
    ('donchian_lower', s.donchian_lower, c.donchian_lower),
    ('donchian_mid',   s.donchian_mid,   c.donchian_mid)
) AS v(indicator, stored, computed)
UNION ALL
SELECT i.symbol, s.timeframe, s.ts, v.indicator, v.stored, v.computed
FROM candle_sma s
JOIN instruments i ON i.id = s.instrument_id
LEFT JOIN candle_indicators_computed c USING (instrument_id, timeframe, ts)
CROSS JOIN LATERAL (VALUES
    ('sma_5',      s.sma_5,      c.sma_5),
    ('sma_20',     s.sma_20,     c.sma_20),
    ('sma_50',     s.sma_50,     c.sma_50),
    ('sma_200',    s.sma_200,    c.sma_200),
    ('sma_5_high', s.sma_5_high, c.sma_5_high),
    ('sma_5_low',  s.sma_5_low,  c.sma_5_low)
) AS v(indicator, stored, computed);

CREATE VIEW dq_indicator_drift AS
SELECT symbol, timeframe, ts, indicator, stored, computed, abs(stored - computed) AS abs_diff
FROM dq_indicator_pairs
WHERE (stored IS NULL) <> (computed IS NULL) OR abs(stored - computed) > 1e-6;

CREATE VIEW dq_indicator_drift_summary AS
SELECT symbol, timeframe, indicator,
       count(*)                                                                     AS rows_compared,
       count(*) FILTER (WHERE (stored IS NULL) <> (computed IS NULL)
                           OR abs(stored - computed) > 1e-6)                        AS rows_drifted,
       count(*) FILTER (WHERE stored IS NULL AND computed IS NOT NULL)              AS stored_missing,
       count(*) FILTER (WHERE stored IS NOT NULL AND computed IS NULL)              AS computed_missing,
       max(abs(stored - computed))                                                  AS max_abs_diff
FROM dq_indicator_pairs
GROUP BY symbol, timeframe, indicator;
