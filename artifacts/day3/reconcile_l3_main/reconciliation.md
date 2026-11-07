# Reconciliation report — FAIL

- Generated: 2026-11-07T18:09:21.339308+00:00
- SQLite source: `data\trading_bot.db`

## Level 3 — backtest parity: FAIL

Window 2025-11-03 → 2026-03-27. The bot's backtester ran on a copy of the source and on a SQLite export of the Postgres compatibility views.

| Run | Trades | Total P&L |
|---|---:|---:|
| Source (SQLite) | 0 | 0.00 |
| Cloud (export of `compat`) | 0 | 0.00 |

- **The source run did not complete:** `backtesting.exceptions.StrictBacktestDataError: Missing exit price(s) at 2025-12-17 14:22:44 for: NIFTY25D2326100PE, NIFTY25D2326100CE`
- **The cloud run did not complete:** `backtesting.exceptions.StrictBacktestDataError: Missing exit price(s) at 2025-12-17 14:22:44 for: NIFTY25D2326100PE, NIFTY25D2326100CE`
- Trades only in the source run: 0
- Trades only in the cloud run: 0
- Trades in both with different values: 0

### Export fidelity (source table vs exported view, row for row)

| Table | Source rows | Export rows | Only in source | Only in export | Identical |
|---|---:|---:|---:|---:|---|
| market_data_1m | 32543 | 32543 | 0 | 0 | yes |
| market_data_5m | 6311 | 6311 | 0 | 0 | yes |
| market_data_15m | 3379 | 3379 | 0 | 0 | yes |
| market_data_1h | 1235 | 1235 | 0 | 0 | yes |
| market_sma_1h | 1235 | 1235 | 0 | 0 | yes |
| vix_data | 2885 | 2885 | 0 | 0 | yes |
| signals | 188 | 188 | 0 | 0 | yes |
| option_data | 336480 | 336480 | 0 | 0 | yes |
| delta_cache | 348109 | 346059 | 2050 | 0 | no |
| dashboard_strategy_state | 3 | 3 | 0 | 0 | yes |
| dashboard_trade_history | 8 | 8 | 0 | 0 | yes |
