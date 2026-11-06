# WAL vs rollback-journal concurrency benchmark

- Generated: 2026-11-06T06:36:48.583132+00:00
- Source: `data\trading_bot.db`
- 10.0 s per mode; writer commits one row every 5.0 ms; reader scans `delta_cache` in a read transaction, back to back; busy timeout 0.5 s

| Journal mode | Writes OK | Write lock errors | Write p50 ms | p95 ms | p99 ms | max ms | Reads OK | Read lock errors | Read p50 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| delete | 14 | 10 | 78.983 | 641.629 | 645.95 | 645.95 | 9 | 0 | 1219.607 |
| wal | 1566 | 0 | 0.98 | 1.407 | 1.938 | 25.971 | 9 | 0 | 1192.01 |
