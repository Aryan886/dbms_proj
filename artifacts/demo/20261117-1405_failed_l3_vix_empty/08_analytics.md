# Analytics views on the main cloud, read as `analyst`

Role: `analyst`

## Strategy P&L summary

| strategy_id | source | closed_trades | wins | losses | win_rate | total_pnl | max_drawdown |
|---|---|---|---|---|---|---|---|
| donchian-options | demo | 2 | 1 | 1 | 0.5000 | 252.50 | 390.00 |
| nifty-options | backtest | 2 | 1 | 1 | 0.5000 | 1230.00 | 1380.00 |
| nifty-options | live-sync | 1 | 1 | 0 | 1.0000 | 2080.00 | 0.00 |
| sma-spread | demo | 2 | 2 | 0 | 1.0000 | 1475.00 | 0.00 |

## P&L by sub-category and exit reason (backfilled backtest)

| dimension | bucket | trades | wins | pnl | win_rate |
|---|---|---|---|---|---|
| (no rows) | | | | | |

## Daily P&L, backfilled backtest, first 10 and last 5 days

| strategy_id | source | trade_day | trades | wins | pnl | cumulative_pnl |
|---|---|---|---|---|---|---|
| (no rows) | | | | | | |

## Data quality: missing 1m candles, totals

| runs | minutes | days |
|---|---|---|
| 7 | 457 | 6 |

## Data quality: the 10 longest runs of missing 1m candles

| symbol | trade_day | first_missing | last_missing | missing_minutes |
|---|---|---|---|---|
| NIFTY50 | 2025-10-21 | 2025-10-21 09:15:00 | 2025-10-21 13:44:00 | 270 |
| NIFTY50 | 2025-10-17 | 2025-10-17 13:16:00 | 2025-10-17 15:29:00 | 134 |
| NIFTY50 | 2025-10-21 | 2025-10-21 14:45:00 | 2025-10-21 15:29:00 | 45 |
| NIFTY50 | 2025-12-18 | 2025-12-18 15:27:00 | 2025-12-18 15:29:00 | 3 |
| NIFTY50 | 2025-12-24 | 2025-12-24 15:27:00 | 2025-12-24 15:29:00 | 3 |
| NIFTY50 | 2025-09-26 | 2025-09-26 15:29:00 | 2025-09-26 15:29:00 | 1 |
| NIFTY50 | 2025-10-10 | 2025-10-10 15:29:00 | 2025-10-10 15:29:00 | 1 |

## Data quality: stale option snapshots (gap > 5 min)

| symbol | trade_day | gap_from | gap_to | gap_minutes |
|---|---|---|---|---|
| NIFTY50 | 2026-03-27 | 2026-03-27 10:29:23 | 2026-03-27 11:31:55 | 62.5 |
| NIFTY50 | 2026-03-27 | 2026-03-27 13:17:03 | 2026-03-27 14:19:11 | 62.1 |
| NIFTY50 | 2026-03-27 | 2026-03-27 09:15:00 | 2026-03-27 10:11:12 | 56.2 |

## Data quality: VIX gaps (> 10 min), totals

| gaps | days | longest |
|---|---|---|
| 0 | 0 |  |

## Data quality: the 10 longest VIX gaps

| trade_day | gap_from | gap_to | gap_minutes |
|---|---|---|---|
| (no rows) | | | |

## Sync: per-table state

| source_table | last_seq | last_applied_at | status | rejected_rows |
|---|---|---|---|---|
| dashboard_strategy_state | 0 |  | active | 0 |
| dashboard_trade_history | 0 |  | active | 0 |
| delta_cache | 686728 | 2026-11-17 14:22:35.468912+05:30 | active | 2050 |
| market_data_15m | 663177 | 2026-11-17 14:22:19.830145+05:30 | active | 0 |
| market_data_1h | 690010 | 2026-11-17 14:22:36.914893+05:30 | active | 0 |
| market_data_1m | 663175 | 2026-11-17 14:22:19.830145+05:30 | active | 0 |
| market_data_5m | 663176 | 2026-11-17 14:22:19.830145+05:30 | active | 0 |
| market_sma_1h | 690820 | 2026-11-17 14:22:36.914893+05:30 | active | 0 |
| option_data | 686684 | 2026-11-17 14:22:35.468912+05:30 | active | 0 |
| signals | 462610 | 2026-11-17 14:19:29.383972+05:30 | active | 0 |
| vix_data | 0 |  | active | 0 |

## Sync: lag by hour (last 5 hours with batches)

| hour | batches | entries | upserts | deletes | rejected | latency_p50_ms | latency_p95_ms | latency_max_ms | lag_max_ms | backlog_at_end |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-17 14:00:00 | 704 | 690820 | 345787 | 345021 | 0 | 326.91 | 885.86 | 2817.12 | 139943.80 | 0 |

## Rejected rows by day

| source_table | day | violated_constraint | rejected |
|---|---|---|---|
| delta_cache | 2026-11-17 | delta_snapshots_pkey | 2050 |
