-- Strategy P&L (spec story 47), per strategy and per trade source, so live
-- trades and backfilled backtest trades are never mixed.
--
-- Only CLOSED trades with a realized P&L count. A win is P&L > 0, a loss < 0.
-- The trading day is the exit's IST calendar day. Max drawdown is the largest
-- fall from a running peak of the closed-trade equity curve (cumulative P&L
-- after each exit, in exit order, starting from 0).

CREATE VIEW analytics.closed_trades AS
SELECT t.id, t.strategy_id, t.source, t.subcat, t.exit_reason, t.entry_ts, t.exit_ts,
       (t.exit_ts AT TIME ZONE 'Asia/Kolkata')::date AS trade_day,
       t.realized_pnl AS pnl
FROM public.dashboard_trade_history t
WHERE t.status = 'CLOSED' AND t.realized_pnl IS NOT NULL AND t.exit_ts IS NOT NULL;

CREATE VIEW analytics.strategy_daily_pnl AS
SELECT strategy_id, source, trade_day,
       count(*)                          AS trades,
       count(*) FILTER (WHERE pnl > 0)   AS wins,
       sum(pnl)                          AS pnl,
       sum(sum(pnl)) OVER (PARTITION BY strategy_id, source ORDER BY trade_day) AS cumulative_pnl
FROM analytics.closed_trades
GROUP BY strategy_id, source, trade_day;

CREATE VIEW analytics.strategy_pnl_summary AS
WITH equity AS (
    SELECT strategy_id, source, exit_ts, id, pnl,
           sum(pnl) OVER curve AS equity
    FROM analytics.closed_trades
    WINDOW curve AS (PARTITION BY strategy_id, source ORDER BY exit_ts, id ROWS UNBOUNDED PRECEDING)
), drawdown AS (
    SELECT *, greatest(0, max(equity) OVER curve) - equity AS below_peak
    FROM equity
    WINDOW curve AS (PARTITION BY strategy_id, source ORDER BY exit_ts, id ROWS UNBOUNDED PRECEDING)
)
SELECT strategy_id, source,
       count(*)                                                AS closed_trades,
       count(*) FILTER (WHERE pnl > 0)                         AS wins,
       count(*) FILTER (WHERE pnl < 0)                         AS losses,
       round(count(*) FILTER (WHERE pnl > 0)::numeric / count(*), 4) AS win_rate,
       sum(pnl)                                                AS total_pnl,
       max(below_peak)                                         AS max_drawdown
FROM drawdown
GROUP BY strategy_id, source;

CREATE VIEW analytics.strategy_pnl_breakdown AS
SELECT strategy_id, source, dimension, bucket,
       count(*)                        AS trades,
       count(*) FILTER (WHERE pnl > 0) AS wins,
       sum(pnl)                        AS pnl,
       round(count(*) FILTER (WHERE pnl > 0)::numeric / count(*), 4) AS win_rate
FROM (
    SELECT strategy_id, source, 'subcat' AS dimension, coalesce(subcat, '(none)') AS bucket, pnl
    FROM analytics.closed_trades
    UNION ALL
    SELECT strategy_id, source, 'exit_reason', coalesce(exit_reason, '(none)'), pnl
    FROM analytics.closed_trades
) b
GROUP BY strategy_id, source, dimension, bucket;
