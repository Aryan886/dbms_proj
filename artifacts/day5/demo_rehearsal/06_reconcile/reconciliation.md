# Reconciliation report — PASS

- Generated: 2026-11-09T18:59:29.204573+00:00
- SQLite source: `C:\Users\aryan\DEV_Maxxing\dbms_proj\data\demo\demo_rehearsal\trading_bot.db`

## Level 1 — row counts: PASS

| Table | SQLite | Postgres | Rejected | Result |
|---|---:|---:|---:|---|
| market_data_1m | 32543 | 32543 | 0 | PASS |
| market_data_5m | 6311 | 6311 | 0 | PASS |
| market_data_15m | 3379 | 3379 | 0 | PASS |
| market_data_1h | 810 | 810 | 0 | PASS |
| market_sma_1h | 810 | 810 | 0 | PASS |
| vix_data | 2885 | 2885 | 0 | PASS |
| signals | 188 | 188 | 0 | PASS |
| option_data | 336480 | 336480 | 0 | PASS |
| delta_cache | 348109 | 346059 | 2050 | PASS |
| dashboard_strategy_state | 3 | 3 | 0 | PASS |
| dashboard_trade_history | 8 | 8 | 0 | PASS |

## Level 2 — per-day checksums: PASS

| Table | Measure | Days | Mismatched days | Result |
|---|---|---:|---:|---|
| market_data_1m | close | 88 | 0 | PASS |
| market_data_5m | close | 85 | 0 | PASS |
| market_data_15m | close | 136 | 0 | PASS |
| market_data_1h | close | 135 | 0 | PASS |
| market_sma_1h | sma_20 | 135 | 0 | PASS |
| vix_data | vix_value | 28 | 0 | PASS |
| signals | confidence_score | 26 | 0 | PASS |
| option_data | ltp | 1 | 0 | PASS |
| delta_cache | delta | 53 | 0 | PASS |
| dashboard_strategy_state | NULL | 3 | 0 | PASS |
| dashboard_trade_history | realized_pnl | 5 | 0 | PASS |

## Level 3 — backtest parity: PASS

Window 2026-03-27 → 2026-03-27. The bot's backtester ran on a copy of the source and on a SQLite export of the Postgres compatibility views.

| Run | Trades | Total P&L |
|---|---:|---:|
| Source (SQLite) | 2 | 637.50 |
| Cloud (export of `compat`) | 2 | 637.50 |

- Trades only in the source run: 0
- Trades only in the cloud run: 0
- Trades in both with different values: 0
- Backtester shim (decision D42, applied to both runs): `BacktestableBot._last_options_snapshot_timestamp = None`

### Export fidelity (source table vs exported view, row for row)

| Table | Source rows | Export rows | Only in source | Only in export | Identical |
|---|---:|---:|---:|---:|---|
| market_data_1m | 32543 | 32543 | 0 | 0 | yes |
| market_data_5m | 6311 | 6311 | 0 | 0 | yes |
| market_data_15m | 3379 | 3379 | 0 | 0 | yes |
| market_data_1h | 810 | 810 | 0 | 0 | yes |
| market_sma_1h | 810 | 810 | 0 | 0 | yes |
| vix_data | 2885 | 2885 | 0 | 0 | yes |
| signals | 188 | 188 | 0 | 0 | yes |
| option_data | 336480 | 336480 | 0 | 0 | yes |
| delta_cache | 348109 | 346059 | 2050 | 0 | no |
| dashboard_strategy_state | 3 | 3 | 0 | 0 | yes |
| dashboard_trade_history | 8 | 8 | 0 | 0 | yes |
