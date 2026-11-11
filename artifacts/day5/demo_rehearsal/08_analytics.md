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
| 153 | 25 | 256.5 |

## Data quality: the 10 longest VIX gaps

| trade_day | gap_from | gap_to | gap_minutes |
|---|---|---|---|
| 2025-11-03 | 2025-11-03 09:15:00 | 2025-11-03 13:31:29 | 256.5 |
| 2026-03-09 | 2026-03-09 12:12:16 | 2026-03-09 14:17:49 | 125.6 |
| 2026-03-04 | 2026-03-04 09:15:00 | 2026-03-04 10:42:58 | 88.0 |
| 2025-12-05 | 2025-12-05 14:11:30 | 2025-12-05 15:30:00 | 78.5 |
| 2026-03-24 | 2026-03-24 10:20:20 | 2026-03-24 11:33:02 | 72.7 |
| 2026-03-18 | 2026-03-18 10:25:58 | 2026-03-18 11:37:02 | 71.1 |
| 2026-03-13 | 2026-03-13 12:15:34 | 2026-03-13 13:23:58 | 68.4 |
| 2026-03-12 | 2026-03-12 12:27:04 | 2026-03-12 13:34:18 | 67.2 |
| 2026-03-12 | 2026-03-12 10:25:37 | 2026-03-12 11:32:49 | 67.2 |
| 2025-11-03 | 2025-11-03 13:31:58 | 2025-11-03 14:37:08 | 65.2 |

## Sync: per-table state

| source_table | last_seq | last_applied_at | status | rejected_rows |
|---|---|---|---|---|
| dashboard_strategy_state | 0 |  | active | 0 |
| dashboard_trade_history | 0 |  | active | 0 |
| delta_cache | 686910 | 2026-11-10 00:29:25.018802+05:30 | active | 2050 |
| market_data_15m | 663355 | 2026-11-10 00:29:09.181011+05:30 | active | 0 |
| market_data_1h | 690192 | 2026-11-10 00:29:26.333953+05:30 | active | 0 |
| market_data_1m | 663353 | 2026-11-10 00:29:09.181011+05:30 | active | 0 |
| market_data_5m | 663354 | 2026-11-10 00:29:09.181011+05:30 | active | 0 |
| market_sma_1h | 691002 | 2026-11-10 00:29:26.333953+05:30 | active | 0 |
| option_data | 686866 | 2026-11-10 00:29:25.018802+05:30 | active | 0 |
| signals | 462752 | 2026-11-10 00:26:37.446349+05:30 | active | 0 |
| vix_data | 678322 | 2026-11-10 00:29:20.502783+05:30 | active | 0 |

## Sync: lag by hour (last 5 hours with batches)

| hour | batches | entries | upserts | deletes | rejected | latency_p50_ms | latency_p95_ms | latency_max_ms | lag_max_ms | backlog_at_end |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-10 00:00:00 | 706 | 691002 | 345892 | 345098 | 0 | 364.42 | 777.40 | 1865.50 | 140644.79 | 0 |

## Rejected rows by day

| source_table | day | violated_constraint | rejected |
|---|---|---|---|
| delta_cache | 2026-11-10 | delta_snapshots_pkey | 2050 |
