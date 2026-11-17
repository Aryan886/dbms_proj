# WAL vs rollback-journal concurrency benchmark

- Generated: 2026-11-17T09:23:33.750650+00:00
- Source: `C:\Users\aryan\DEV_Maxxing\dbms_proj\data\demo\20261117_1435\trading_bot.db`
- 3.0 s per mode; writer commits one row every 5.0 ms; reader scans `delta_cache` in a read transaction, back to back; busy timeout 5.0 s

| Journal mode | Writes OK | Write lock errors | Write p50 ms | p95 ms | p99 ms | max ms | Reads OK | Read lock errors | Read p50 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| delete | 2 | 0 | 1419.126 | 1585.871 | 1585.871 | 1585.871 | 3 | 0 | 1366.301 |
| wal | 446 | 0 | 1.092 | 1.775 | 10.705 | 29.111 | 3 | 0 | 1289.167 |
