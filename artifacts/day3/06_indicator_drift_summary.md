# Stored vs SQL-computed indicators (main cloud database, `dq_indicator_drift_summary`)

Query time: 6.59 s. Drift = a value on one side only, or |stored - computed| > 1e-6.

| Timeframe | Indicator | Rows compared | Rows drifted | Stored missing | Computed missing | Max abs diff |
|---|---|---:|---:|---:|---:|---:|
| 15m | ao_value | 3379 | 1588 | 1588 | 0 | 0.0000 |
| 15m | donchian_lower | 3379 | 1064 | 1064 | 0 | 0.0000 |
| 15m | donchian_mid | 3379 | 1064 | 1064 | 0 | 0.0000 |
| 15m | donchian_upper | 3379 | 1064 | 1064 | 0 | 0.0000 |
| 1h | ao_value | 1235 | 47 | 47 | 0 | 0.0000 |
| 1h | donchian_lower | 1235 | 33 | 33 | 0 | 0.0000 |
| 1h | donchian_mid | 1235 | 33 | 33 | 0 | 0.0000 |
| 1h | donchian_upper | 1235 | 33 | 33 | 0 | 0.0000 |
| 1h | sma_20 | 1235 | 33 | 0 | 0 | 272.9225 |
| 1h | sma_200 | 1235 | 213 | 0 | 0 | 242.7709 |
| 1h | sma_5 | 1235 | 12 | 0 | 0 | 124.3300 |
| 1h | sma_50 | 1235 | 63 | 0 | 0 | 427.2247 |
| 1h | sma_5_high | 1235 | 12 | 0 | 0 | 86.1100 |
| 1h | sma_5_low | 1235 | 12 | 0 | 0 | 126.5400 |
| 1m | ao_value | 32543 | 1320 | 1320 | 0 | 0.0000 |
| 1m | donchian_lower | 32543 | 760 | 760 | 0 | 0.0000 |
| 1m | donchian_mid | 32543 | 760 | 760 | 0 | 0.0000 |
| 1m | donchian_upper | 32543 | 760 | 760 | 0 | 0.0000 |
| 5m | ao_value | 6311 | 1464 | 1464 | 0 | 0.0000 |
| 5m | donchian_lower | 6311 | 848 | 848 | 0 | 0.0000 |
| 5m | donchian_mid | 6311 | 848 | 848 | 0 | 0.0000 |
| 5m | donchian_upper | 6311 | 848 | 848 | 0 | 0.0000 |
