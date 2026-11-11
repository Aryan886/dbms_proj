# Demo run demo_rehearsal

**Result: PASS** in 16.9 min. Demo pair: its own working copy (from the bot's database, read-only) and Postgres database `cloudsync_demo_demo_rehearsal` on `localhost` (dropped afterwards).

| # | Step | Exit | OK | Seconds | Artifact |
|---|---|---|---|---|---|
| 0 | Real database SHA-256 (before) | 0 | yes | 4.7 | [00_real_db_sha256_before.txt](00_real_db_sha256_before.txt) |
| 1 | VACUUM study (prep) | 0 | yes | 54.3 | [01_prep_vacuum.log](01_prep_vacuum.log) |
| 2 | Cloud schema (migrate) | 0 | yes | 2.3 | [02_migrate.log](02_migrate.log) |
| 3 | CDC install (WAL, triggers, fingerprints) | 0 | yes | 1.1 | [03_cdc_install.log](03_cdc_install.log) |
| 4 | Bulk load | 0 | yes | 427.7 | [04_bulk_load.log](04_bulk_load.log) |
| 5 | Replay 2026-03-27 with chaos revise,rebuild,kill (sync as sync_writer) | 0 | yes | 429.5 | [05_replay_chaos.log](05_replay_chaos.log) |
| 5b | Final sync once (as sync_writer) | 0 | yes | 1.0 | [05b_final_sync.log](05b_final_sync.log) |
| 6 | Reconciliation L1-L3 (2026-03-27) | 0 | yes | 83.2 | [06_reconcile.log](06_reconcile.log) |
| 7 | Roles: reads allowed, writes denied | 0 | yes | 0.1 | [07_roles.json](07_roles.json) |
| 8 | Analytics as analyst | 0 | yes | 2.2 | [08_analytics.log](08_analytics.log) |
| 8b | Dead tuples vs SQLite free pages | 0 | yes | 0.7 | [08b_dead_tuples.log](08b_dead_tuples.log) |
| 9 | Real database SHA-256 (after) unchanged | 0 | yes | 4.7 | [09_real_db_sha256_after.txt](09_real_db_sha256_after.txt) |

## Add-ons over the original bot (story 52)

Everything below is an **ADD-ON**: the bot's code and its database are unchanged.

| Add-on | What it changes | Evidence bot behaviour didn't change |
|---|---|---|
| **ADD-ON:** VACUUM of the working copy | free pages reclaimed in the copy (step 1) | the bot's own file is only read (SHA-256 identical before/after, step 9) |
| **ADD-ON:** WAL mode on the working copy | readers no longer block the bot's writer (Day-2 bench-wal) | the bot's own writers ran unchanged in the replay (step 5); L3 PASS (step 6) |
| **ADD-ON:** Normalized, typed cloud schema (3NF, NUMERIC prices, option header/line) | storage and integrity in the cloud | compat views give the bot its original tables; L1/L2 PASS and L3 identical trades (step 6) |
| **ADD-ON:** Change data capture + exactly-once sync | the cloud follows every insert/update/delete | the triggers only append to _changelog; L1-L3 PASS after a killed sync (steps 5-6) |
| **ADD-ON:** Expression B-tree indexes on IST time (D63) | latest-N candle query 12.3 -> 1.7 ms (Day-4 index audit) | same query, same rows through compat (test_compat_views); cloud only |
| **ADD-ON:** Least-privilege roles + audit trail | who may read/write what; who changed trades | cloud only; the bot reader still reads its views (step 7) |
| **ADD-ON:** Analytics views (P&L, data quality, sync lag) | SQL reporting | read-only views; nothing writes back to the bot |
| **ADD-ON:** Dropping the duplicate idx_ indexes in SQLite | 1.58 MB saved, same plan (Day-4, sandbox only) | NOT applied to the bot's database (D64): the owner's call |
