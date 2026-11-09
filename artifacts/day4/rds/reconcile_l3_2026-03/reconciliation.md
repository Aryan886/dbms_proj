# Reconciliation report — PASS

- Generated: 2026-11-08T16:15:30.167855+00:00
- SQLite source: `data\trading_bot.db`

## Level 3 — backtest parity: PASS

Window 2026-03-02 → 2026-03-27. The bot's backtester ran on a copy of the source and on a SQLite export of the Postgres compatibility views.

| Run | Trades | Total P&L |
|---|---:|---:|
| Source (SQLite) | 74 | 17271.25 |
| Cloud (export of `compat`) | 74 | 17271.25 |

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
| market_data_1h | 1235 | 1235 | 0 | 0 | yes |
| market_sma_1h | 1235 | 1235 | 0 | 0 | yes |
| vix_data | 2885 | 2885 | 0 | 0 | yes |
| signals | 188 | 188 | 0 | 0 | yes |
| option_data | 336480 | 336480 | 0 | 0 | yes |
| delta_cache | 348109 | 346059 | 2050 | 0 | no |
| dashboard_strategy_state | 3 | 3 | 0 | 0 | yes |
| dashboard_trade_history | 8 | 8 | 0 | 0 | yes |
