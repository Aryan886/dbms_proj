# Reconciliation report — FAIL

- Generated: 2026-11-17T08:52:39.741052+00:00
- SQLite source: `C:\Users\aryan\DEV_Maxxing\dbms_proj\data\demo\20261117_1405\trading_bot.db`

## Level 1 — row counts: PASS

| Table | SQLite | Postgres | Rejected | Result |
|---|---:|---:|---:|---|
| market_data_1m | 32543 | 32543 | 0 | PASS |
| market_data_5m | 6311 | 6311 | 0 | PASS |
| market_data_15m | 3379 | 3379 | 0 | PASS |
| market_data_1h | 810 | 810 | 0 | PASS |
| market_sma_1h | 810 | 810 | 0 | PASS |
| vix_data | 0 | 0 | 0 | PASS |
| signals | 191 | 191 | 0 | PASS |
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
| vix_data | vix_value | 0 | 0 | PASS |
| signals | confidence_score | 27 | 0 | PASS |
| option_data | ltp | 1 | 0 | PASS |
| delta_cache | delta | 53 | 0 | PASS |
| dashboard_strategy_state | NULL | 3 | 0 | PASS |
| dashboard_trade_history | realized_pnl | 5 | 0 | PASS |

## Level 3 — backtest parity: FAIL

Window 2026-03-27 → 2026-03-27. The bot's backtester ran on a copy of the source and on a SQLite export of the Postgres compatibility views.

| Run | Trades | Total P&L |
|---|---:|---:|
| Source (SQLite) | 0 | 0.00 |
| Cloud (export of `compat`) | 0 | 0.00 |

- **The source run did not complete:** `backtesting.exceptions.BacktestDataCoverageError: vix_data does not fully cover the required backtest window 2026-03-27 09:15:00 -> 2026-03-27 15:00:00. Available: no data. The strategy hard-blocks entries when VIX regime cannot be determined, so this coverage gap would otherwise show repeated 'VIX data missing; cannot determine VIX regime.' warnings and produce zero trades.`
- **The cloud run did not complete:** `backtesting.exceptions.BacktestDataCoverageError: vix_data does not fully cover the required backtest window 2026-03-27 09:15:00 -> 2026-03-27 15:00:00. Available: no data. The strategy hard-blocks entries when VIX regime cannot be determined, so this coverage gap would otherwise show repeated 'VIX data missing; cannot determine VIX regime.' warnings and produce zero trades.`
- Trades only in the source run: 0
- Trades only in the cloud run: 0
- Trades in both with different values: 0

### Export fidelity (source table vs exported view, row for row)

| Table | Source rows | Export rows | Only in source | Only in export | Identical |
|---|---:|---:|---:|---:|---|
| market_data_1m | 32543 | 32543 | 0 | 0 | yes |
| market_data_5m | 6311 | 6311 | 0 | 0 | yes |
| market_data_15m | 3379 | 3379 | 0 | 0 | yes |
| market_data_1h | 810 | 810 | 0 | 0 | yes |
| market_sma_1h | 810 | 810 | 0 | 0 | yes |
| vix_data | 0 | 0 | 0 | 0 | yes |
| signals | 191 | 191 | 0 | 0 | yes |
| option_data | 336480 | 336480 | 0 | 0 | yes |
| delta_cache | 348109 | 346059 | 2050 | 0 | no |
| dashboard_strategy_state | 3 | 3 | 0 | 0 | yes |
| dashboard_trade_history | 8 | 8 | 0 | 0 | yes |
