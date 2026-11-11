# Analytics views on the main cloud, read as `analyst`

Role: `analyst`

## Strategy P&L summary

| strategy_id | source | closed_trades | wins | losses | win_rate | total_pnl | max_drawdown |
|---|---|---|---|---|---|---|---|
| donchian-options | demo | 2 | 1 | 1 | 0.5000 | 252.50 | 390.00 |
| nifty-options | backtest | 2 | 1 | 1 | 0.5000 | 1230.00 | 1380.00 |
| nifty-options | backtest-backfill | 90 | 38 | 50 | 0.4222 | 12620.00 | 7783.75 |
| nifty-options | live-sync | 1 | 1 | 0 | 1.0000 | 2080.00 | 0.00 |
| sma-spread | demo | 2 | 2 | 0 | 1.0000 | 1475.00 | 0.00 |

## P&L by sub-category and exit reason (backfilled backtest)

| dimension | bucket | trades | wins | pnl | win_rate |
|---|---|---|---|---|---|
| exit_reason | TIME_EXIT | 13 | 11 | 21812.50 | 0.8462 |
| exit_reason | SL_HIT | 77 | 27 | -9192.50 | 0.3506 |
| subcat | g | 4 | 3 | 15953.75 | 0.7500 |
| subcat | b | 4 | 2 | 73.75 | 0.5000 |
| subcat | (none) | 2 | 0 | -143.75 | 0.0000 |
| subcat | a | 80 | 33 | -3263.75 | 0.4125 |

## Daily P&L, backfilled backtest, first 10 and last 5 days

| strategy_id | source | trade_day | trades | wins | pnl | cumulative_pnl |
|---|---|---|---|---|---|---|
| nifty-options | backtest-backfill | 2025-11-07 | 4 | 0 | -1048.75 | -1048.75 |
| nifty-options | backtest-backfill | 2025-12-10 | 4 | 2 | 208.75 | -840.00 |
| nifty-options | backtest-backfill | 2025-12-11 | 8 | 2 | -3811.25 | -4651.25 |
| nifty-options | backtest-backfill | 2026-03-04 | 2 | 0 | -2030.00 | -6681.25 |
| nifty-options | backtest-backfill | 2026-03-05 | 6 | 3 | -448.75 | -7130.00 |
| nifty-options | backtest-backfill | 2026-03-06 | 2 | 1 | 4495.00 | -2635.00 |
| nifty-options | backtest-backfill | 2026-03-09 | 2 | 0 | -2597.50 | -5232.50 |
| nifty-options | backtest-backfill | 2026-03-10 | 12 | 4 | -1467.50 | -6700.00 |
| nifty-options | backtest-backfill | 2026-03-11 | 4 | 4 | 11691.25 | 4991.25 |
| nifty-options | backtest-backfill | 2026-03-12 | 8 | 2 | -310.00 | 4681.25 |
| nifty-options | backtest-backfill | 2026-03-16 | 6 | 4 | 477.50 | 6590.00 |
| nifty-options | backtest-backfill | 2026-03-19 | 6 | 2 | 7241.25 | 13831.25 |
| nifty-options | backtest-backfill | 2026-03-20 | 6 | 6 | 1447.50 | 15278.75 |
| nifty-options | backtest-backfill | 2026-03-24 | 6 | 0 | -3152.50 | 12126.25 |
| nifty-options | backtest-backfill | 2026-03-27 | 4 | 2 | 493.75 | 12620.00 |

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
| delta_cache | 686910 | 2026-11-09 23:52:10.055931+05:30 | active | 2050 |
| market_data_15m | 663355 | 2026-11-09 23:51:47.045510+05:30 | active | 0 |
| market_data_1h | 690192 | 2026-11-09 23:52:12.895811+05:30 | active | 0 |
| market_data_1m | 663353 | 2026-11-09 23:51:47.045510+05:30 | active | 0 |
| market_data_5m | 663354 | 2026-11-09 23:51:47.045510+05:30 | active | 0 |
| market_sma_1h | 691002 | 2026-11-09 23:52:12.895811+05:30 | active | 0 |
| option_data | 686866 | 2026-11-09 23:52:10.055931+05:30 | active | 0 |
| signals | 462752 | 2026-11-09 23:47:58.554984+05:30 | active | 0 |
| vix_data | 678322 | 2026-11-09 23:52:03.155838+05:30 | active | 0 |

## Sync: lag by hour (last 5 hours with batches)

| hour | batches | entries | upserts | deletes | rejected | latency_p50_ms | latency_p95_ms | latency_max_ms | lag_max_ms | backlog_at_end |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-09 23:00:00 | 706 | 691002 | 345892 | 345098 | 0 | -709.00 | 72.89 | 897.11 | 189276.94 | 0 |

## Rejected rows by day

| source_table | day | violated_constraint | rejected |
|---|---|---|---|
| delta_cache | 2026-11-08 | delta_snapshots_pkey | 2019 |
| delta_cache | 2026-11-09 | delta_snapshots_pkey | 31 |
