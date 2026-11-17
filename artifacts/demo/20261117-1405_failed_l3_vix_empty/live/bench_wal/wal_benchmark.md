# WAL vs rollback-journal concurrency benchmark

- Generated: 2026-11-17T08:56:25.084689+00:00
- Source: `C:\Users\aryan\DEV_Maxxing\dbms_proj\data\demo\20261117_1405\trading_bot.db`
- 3.0 s per mode; writer commits one row every 5.0 ms; reader scans `delta_cache` in a read transaction, back to back; busy timeout 5.0 s

| Journal mode | Writes OK | Write lock errors | Write p50 ms | p95 ms | p99 ms | max ms | Reads OK | Read lock errors | Read p50 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| delete | 6 | 0 | 6.041 | 1308.744 | 1308.744 | 1308.744 | 3 | 0 | 1243.688 |
| wal | 462 | 0 | 1.108 | 1.676 | 1.896 | 6.69 | 3 | 0 | 1349.146 |
