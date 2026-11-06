# WAL vs rollback-journal concurrency benchmark

- Generated: 2026-11-06T06:36:11.877650+00:00
- Source: `data\trading_bot.db`
- 10.0 s per mode; writer commits one row every 5.0 ms; reader scans `delta_cache` in a read transaction, back to back; busy timeout 5.0 s

| Journal mode | Writes OK | Write lock errors | Write p50 ms | p95 ms | p99 ms | max ms | Reads OK | Read lock errors | Read p50 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| delete | 16 | 0 | 1203.273 | 1329.94 | 1330.27 | 1330.27 | 8 | 0 | 1274.089 |
| wal | 1569 | 0 | 0.981 | 1.479 | 1.867 | 23.138 | 9 | 0 | 1194.285 |
