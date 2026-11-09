# Reconciliation report — PASS

- Generated: 2026-11-08T10:31:05.000900+00:00
- SQLite source: `data\trading_bot.db`

## Level 1 — row counts: PASS

| Table | SQLite | Postgres | Rejected | Result |
|---|---:|---:|---:|---|
| market_data_1m | 32543 | 32543 | 0 | PASS |
| market_data_5m | 6311 | 6311 | 0 | PASS |
| market_data_15m | 3379 | 3379 | 0 | PASS |
| market_data_1h | 1235 | 1235 | 0 | PASS |
| market_sma_1h | 1235 | 1235 | 0 | PASS |
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
| market_data_1h | close | 186 | 0 | PASS |
| market_sma_1h | sma_20 | 186 | 0 | PASS |
| vix_data | vix_value | 28 | 0 | PASS |
| signals | confidence_score | 26 | 0 | PASS |
| option_data | ltp | 1 | 0 | PASS |
| delta_cache | delta | 53 | 0 | PASS |
| dashboard_strategy_state | NULL | 3 | 0 | PASS |
| dashboard_trade_history | realized_pnl | 5 | 0 | PASS |
