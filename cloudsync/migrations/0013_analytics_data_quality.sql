-- Data-quality views (spec story 49). Market hours are 09:15-15:30 IST; the
-- last 1m candle of a session starts at 15:29 (375 candles, as in the real data).
--
-- A day is checked for a feed only if that feed has data on that day, so
-- holidays and days before a feed existed aren't reported as one long gap.
-- Thresholds come from the real cadence (Day 4 log): option chains arrive every
-- 0.6-1.6 min, VIX about every 5.3-5.7 min.

-- Missing 1m candles, collapsed into runs of consecutive minutes (gaps and
-- islands: minute minus its rank is constant inside a run).
CREATE VIEW analytics.dq_missing_1m_candles AS
WITH days AS (
    SELECT DISTINCT c.instrument_id, (c.ts AT TIME ZONE 'Asia/Kolkata')::date AS trade_day
    FROM public.candles c WHERE c.timeframe = '1m'
), missing AS (
    SELECT d.instrument_id, d.trade_day, m AS minute
    FROM days d
    CROSS JOIN LATERAL generate_series(d.trade_day + time '09:15', d.trade_day + time '15:29',
                                       interval '1 minute') AS m
    WHERE NOT EXISTS (SELECT FROM public.candles c
                      WHERE c.instrument_id = d.instrument_id AND c.timeframe = '1m'
                        AND c.ts = m AT TIME ZONE 'Asia/Kolkata')
), runs AS (
    SELECT *, minute - row_number() OVER (PARTITION BY instrument_id, trade_day ORDER BY minute)
                       * interval '1 minute' AS run
    FROM missing
)
SELECT i.symbol, r.trade_day, min(r.minute) AS first_missing, max(r.minute) AS last_missing,
       count(*) AS missing_minutes
FROM runs r JOIN public.instruments i ON i.id = r.instrument_id
GROUP BY i.symbol, r.trade_day, r.run;

-- Gaps between consecutive observations inside market hours. The session open
-- and close count as observations, so a feed that starts late or stops early
-- shows up as a gap too.
CREATE VIEW analytics.dq_stale_option_snapshots AS
WITH obs AS (
    SELECT instrument_id, ts AT TIME ZONE 'Asia/Kolkata' AS t FROM public.option_chain_snapshots
), in_hours AS (
    SELECT instrument_id, t::date AS trade_day, t FROM obs WHERE t::time BETWEEN time '09:15' AND time '15:30'
), points AS (
    SELECT instrument_id, trade_day, t FROM in_hours
    UNION SELECT instrument_id, trade_day, trade_day + time '09:15' FROM in_hours
    UNION SELECT instrument_id, trade_day, trade_day + time '15:30' FROM in_hours
), gaps AS (
    SELECT instrument_id, trade_day, lag(t) OVER (PARTITION BY instrument_id, trade_day ORDER BY t) AS gap_from,
           t AS gap_to
    FROM points
)
SELECT i.symbol, g.trade_day, g.gap_from, g.gap_to,
       round(extract(epoch FROM g.gap_to - g.gap_from) / 60, 1) AS gap_minutes
FROM gaps g JOIN public.instruments i ON i.id = g.instrument_id
WHERE g.gap_to - g.gap_from > interval '5 minutes';

CREATE VIEW analytics.dq_vix_gaps AS
WITH in_hours AS (
    SELECT t::date AS trade_day, t
    FROM (SELECT ts AT TIME ZONE 'Asia/Kolkata' AS t FROM public.vix_observations) o
    WHERE t::time BETWEEN time '09:15' AND time '15:30'
), points AS (
    SELECT trade_day, t FROM in_hours
    UNION SELECT trade_day, trade_day + time '09:15' FROM in_hours
    UNION SELECT trade_day, trade_day + time '15:30' FROM in_hours
), gaps AS (
    SELECT trade_day, lag(t) OVER (PARTITION BY trade_day ORDER BY t) AS gap_from, t AS gap_to FROM points
)
SELECT trade_day, gap_from, gap_to, round(extract(epoch FROM gap_to - gap_from) / 60, 1) AS gap_minutes
FROM gaps
WHERE gap_to - gap_from > interval '10 minutes';

-- Day 3's indicator-drift views, exposed to the analyst.
CREATE VIEW analytics.dq_indicator_drift AS SELECT * FROM public.dq_indicator_drift;
CREATE VIEW analytics.dq_indicator_drift_summary AS SELECT * FROM public.dq_indicator_drift_summary;
