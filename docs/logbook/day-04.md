# Day 4 — Roles, audit trigger, index audit, analytics, P&L backfill, RDS (2026-11-08)

**Goal (from the spec's day plan):** three least-privilege roles and a denied write (stories
42–43); an audit trigger on trade history and strategy state (44); an index audit with
EXPLAIN ANALYZE, B-tree vs BRIN, and the duplicate `idx_`/`ux_` pairs (40); the strategy P&L,
data-quality and sync-lag views (47, 49, 50); the trade history filled from backtest output
(48); the switch to RDS with credentials kept out of git (46). Carried from Day 3: a
single-daemon lock.

**Outcome:** ✅ Done. **`PG_DSN` now points at RDS** (owner's OK, D66). Everything is tested
or measured on the Docker main pair (**L1/L2 PASS 11/11** after every change). The owner created
RDS with the wizard (`scripts/rds_setup_wizard.sh`, 4.8), and it's loaded: **L1/L2 PASS 11/11 and
L3 PASS (74 trades, identical) on RDS**. Sandbox chaos replay as `sync_writer`: **L1–L3 PASS**.
Full suite **57 tests, all pass**. Real database unchanged.

---

## 1. What was built

| # | Slice | Driving test | Main files |
|---|---|---|---|
| 1 | Tracer bullet: `bot_reader` reads `compat`, is denied writes and base tables | `test_bot_reader_reads_the_compat_views_but_is_denied_writes` | `migrations/0010_roles.sql`, `tests/test_roles.py` |
| 2 | `sync_writer`: read/write on the `public` base tables only (table by table, not views); `sync once` runs as it | `test_sync_runs_as_sync_writer_which_cannot_read_the_consumer_views` (mutation-checked, 4.2) | `0010` |
| 3 | Audit trigger on `dashboard_trade_history` + `dashboard_strategy_state` into `audit.audit_log` (actor, login, txid, old/new JSON); no-op upserts not logged; `sync_writer` may only INSERT into the log | `test_synced_trade_and_strategy_changes_are_audited_with_old_and_new_rows`, `test_sync_writer_cannot_rewrite_the_audit_trail` (mutation-checked) | `migrations/0011_audit_trigger.sql`, `tests/test_audit.py` |
| 4 | `analyst` role + `analytics` schema; strategy P&L views (daily + cumulative, summary with win rate and max drawdown, breakdown by sub-category / exit reason), per strategy **and source** | `test_daily_and_cumulative_pnl`, `test_summary_has_win_rate_and_max_drawdown`, `test_pnl_by_sub_category_and_exit_reason` (values worked by hand) | `migrations/0012_analytics_pnl.sql`, `tests/test_analytics.py` |
| 5 | Role boundaries: analyst can't read base/compat, bot_reader can't read analytics | `test_analyst_reads_only_the_analytics_views` (green on first run, see 4.3) | `0010` |
| 6 | Data quality: missing 1m candles as runs (gaps and islands), stale option snapshots (> 5 min), VIX gaps (> 10 min), in market hours; Day-3 drift views exposed in `analytics` | `test_missing_1m_candles_are_reported_as_runs_of_minutes` (mutation-checked), `test_vix_gaps_longer_than_ten_minutes_in_market_hours`, `test_stale_option_snapshots_gaps_longer_than_five_minutes` | `migrations/0013_analytics_data_quality.sql` |
| 7 | Sync lag: the sync records the changelog backlog with each batch; views for batches, per-table state, rejects by day, lag by hour | `test_sync_lag_views_show_batches_backlog_last_seq_and_rejects` (mutation-checked) | `migrations/0014_sync_lag_views.sql`, `cloudsync/sync.py` |
| 8 | Single-sync lock: session advisory lock; a second `sync once`/`daemon` is REFUSED; a killed daemon releases it | `test_a_second_sync_is_refused_while_a_daemon_runs_and_allowed_after_it_dies` | `cloudsync/sync.py`, `tests/support.py` (`run_cli(timeout=)`) |
| 9 | `bench-indexes`: EXPLAIN ANALYZE of the bot's query shapes on `compat` under 5 index variants, each rolled back | measurement (spec: benchmarks aren't tests) | `cloudsync/index_audit.py`, `cli.py` |
| 10 | Adopted indexes from the audit: B-tree on `ts AT TIME ZONE 'Asia/Kolkata'` for `candles` and `delta_snapshots` | measurement + full suite | `migrations/0016_ist_expression_indexes.sql` |
| 11 | Duplicate `idx_`/`ux_` study on a sandbox SQLite copy | measurement | `scripts/sqlite_duplicate_indexes.py` |
| 12 | `backfill-trades`: unchanged backtester on a copy → tagged rows (negative id, `source='backtest-backfill'`) in the cloud's trade history; compat and L1/L2 cover only `id > 0` | **no automated test (D52)**; real runs below, existing compat/reconcile tests still pass | `cloudsync/backfill.py`, `migrations/0015_…`, `0017_…`, `tables.py` |
| 13 | RDS setup wizard (5 stages: region, create, endpoint + backups, inbound rule, TLS connection test → `RDS_*` in `.env`) | `bash -n`; not run (needs the owner) | `scripts/rds_setup_wizard.sh`, `.env.example` |
| — | Analytics report read as `analyst` | manual, real run | `scripts/analytics_report.py` |

**How the roles work** (the explanation to give the examiner): three NOLOGIN group roles,
created once per server (roles are cluster-wide) and granted per database in migration 0010.
A consumer connects as a member, or with `options=-c role=<name>`, which is how the tests and
`sync once` do it. `bot_reader` has USAGE on `compat` and SELECT on its views; `analyst` has
USAGE on `analytics` and SELECT on its views (default privileges cover later views);
`sync_writer` has SELECT/INSERT/UPDATE/DELETE on each base table in `public`, granted table by
table so the views in `public` stay out of reach. Views run with their owner's rights, so
neither reader needs any grant on the base tables behind them. Postgres enforces all of it:
the denied write raises `InsufficientPrivilege`.

**How the audit trail works:** `AFTER INSERT/UPDATE/DELETE … FOR EACH ROW` triggers write
`to_jsonb(OLD)` / `to_jsonb(NEW)` into `audit.audit_log`, with `current_user` (the role that
made the change), `session_user`, `txid_current()` and `clock_timestamp()`. The UPDATE trigger
has `WHEN (OLD.* IS DISTINCT FROM NEW.*)`, because the sync re-applies rows as upserts. The
function runs with the caller's rights, so `actor` really is `sync_writer`. That role may only
INSERT into the log, so it can't read, rewrite or delete the trail it leaves.

## 2. Decisions taken

| # | Decision | Owner | Alternatives considered | Why |
|---|---|---|---|---|
| D50 | **Backfilled trades go to the cloud only**, tagged; SQLite untouched | Team | Write through the bot's dashboard store into the working copy; sandbox only | Owner's choice; keeps the main working copy pipeline-only |
| D51 | **RDS is created by the owner with a wizard**; the switch happens once RDS is migrated, loaded and reconciled | Team | Owner already has an instance; defer to Day 5 | Owner's choice ("not created; guide me") |
| D52 | Day-4 test seams: roles, audit trigger, analytics views (+ the single-sync lock). Backfill and index audit are measured, not tested | Team | Also test the backfill (runs the real backtester, minutes per test) | Owner's choice of seams |
| D53 | Extra Day-4 scope: the single-daemon lock only (not the dead-tuple study or bulk-load profiling) | Team | Also story 41, Day-2 profiling | Owner's choice |
| D54 | Roles are NOLOGIN group roles, created `IF NOT EXISTS`, granted per database; consumers use membership or `-c role=` | Agent | LOGIN roles with passwords in the migration | No secret in a migration; roles are cluster-wide and shared by the test databases |
| D55 | `sync_writer` is granted table by table on `public` base tables (a helper function later migrations call), not `ON ALL TABLES` | Agent | `ON ALL TABLES` + default privileges | `public` also holds views (indicators, drift), which the writer must not read |
| D56 | Audit log in its own schema `audit`; function not SECURITY DEFINER; writer gets INSERT only | Agent | Log in `public`; SECURITY DEFINER | No grant on `public` can reach the log; `actor` is the real role; the trail is append-only for the pipeline |
| D57 | P&L views split by `(strategy_id, source)`; only CLOSED trades with a realized P&L; trading day = exit's IST date; max drawdown on the closed-trade equity curve from 0 | Agent | Mix sources; daily-level drawdown | Backfilled and live trades must never mix (4.5 shows why); trade-level drawdown is the finer, standard measure |
| D58 | Data-quality thresholds from the measured cadence: option snapshot gap > 5 min, VIX gap > 10 min, market hours 09:15–15:30 with open/close as boundary points; a feed is checked only on days it has data | Agent | Fixed config table; flag whole missing days | Real cadence: chains 0.6–1.6 min, VIX 5.3–5.7 min, 375 1m candles 09:15–15:29 (section 3) |
| D59 | The sync records the backlog after each batch (`sync_batches.backlog_after`), read in the batch's SQLite snapshot and committed with it | Agent | A separate status write after prune | Postgres can't see the SQLite changelog; one transaction keeps it consistent |
| D60 | Single-sync lock = session-level `pg_try_advisory_lock` on the sync's connection; a second sync exits `REFUSED` | Agent | Lock file; standby that waits | Released by Postgres when the session ends, even on `kill -9`; per database, so sandboxes don't block the main sync |
| D61 | Backfilled rows: **negative ids** + `source='backtest-backfill'` (CHECK enforces the pair); `compat` view and L1/L2 for trade history cover `id > 0` | Agent (implements D50) | Separate `backtest_trades` table; accept an L1 FAIL | The sync only writes positive ids, so it can never touch them; the bot still sees exactly its own rows; reconcile stays meaningful |
| D62 | Backtest → dashboard mapping: side BUY for a net debit, qty = \|entry total\| / \|net leg premium\| (50 on every real trade), per-unit prices, the bot's flat record for section/subcat/SL/exit reason | Agent | Sum of leg quantities (legs have none); totals as prices | Keeps the dashboard's identity (exit − entry) × qty = P&L (max deviation 0.50 from 2-dp rounding) |
| D63 | Index choice from the audit: **B-tree on `ts AT TIME ZONE 'Asia/Kolkata'`** for `candles` and `delta_snapshots`; no BRIN | Agent | BRIN on `ts` or on the expression; no change | Measured (section 3): B-tree beats BRIN on the bot's top-N and point lookups; BRIN on raw `ts` is never used because the views filter on the expression |
| D64 | The duplicate `idx_` indexes are **not dropped in the bot's database** (read-only, D28); measured on a sandbox copy; the cloud schema never had them | Agent (implements D28) | Drop them in the working copy | The working copy mirrors the bot; changing the bot's schema is the owner's call |
| D65 | RDS wizard writes `RDS_*` keys only; `PG_DSN` keeps pointing at Docker until RDS reconciles | Agent | Overwrite `PG_DSN` in the wizard | The main pair never points at an empty database |
| D66 | **Main cloud switched to RDS**: `PG_DSN` = RDS, the Docker main cloud kept as `DOCKER_PG_DSN` (no longer synced); tests stay on Docker (`PG_ADMIN_DSN`) | Team | Keep syncing both | The working copy's single changelog is pruned by whichever cloud syncs, so only one can be kept current; Day 5's PITR needs RDS live |

## 3. Measurements (real runs only)
| Metric | Value | Artifact |
|---|---|---|
| Main cloud brought to Day 4 | `migrate` applied 10–15 in 1.3 s, then 16 and 17 | `artifacts/day4/01_migrate_main.log` |
| `sync once` on the main pair **as `sync_writer`** | ran; idle (0 entries, backlog 0) | `02_sync_once_as_sync_writer.log` |
| Reconciliation, main pair, after migrations 10–15 | **L1 PASS 11/11, L2 PASS 11/11**, 3.4 s | `reconcile_l1_l2/` |
| Feed cadence (read-only on the working copy) | 1m: 82 of 88 days have 375 candles 09:15–15:29; option chains only on 2026-03-27 (160 snapshots, gaps mostly 0.6–1.6 min); VIX gaps mostly 0.3 or 5.3–5.7 min | scratch query; same day's gaps in `10_analytics_main.md` |
| **Index audit**, sandbox clone of the main cloud, median of 5 `EXPLAIN (ANALYZE, BUFFERS)` | latest 200 1m candles: baseline 12.3 ms, BRIN(ts) 12.2, B-tree(ts) 12.4, **B-tree(IST expr) 1.7**, BRIN(IST expr) 5.8 · latest delta rows: 175.9 → **0.13** (B-tree expr) vs 3.2 (BRIN expr) · full-range backtest read ~155–162 ms in every variant (seq scan, 32,543 rows) · `MAX(timestamp)` option 384–409 ms, delta 149–151 ms in every variant | `index_audit/index_audit.md`, `.json` |
| Index sizes | BRIN 24,576 B each; B-tree candles 1,384,448 B, delta 2,678,784 B; `pg_stats` correlation of `ts`: candles 0.548, delta_snapshots 1.0 | same; `05_index_audit.log` |
| SQLite duplicate `idx_` indexes (sandbox copy, after VACUUM) | dropping the 3 `idx_market_data_*` saves **1,581,056 B (386 pages)**, 88.56 → 86.98 MB; the bot's query plan is the same before and after (it already uses `ux_market_data_1m_symbol_timestamp`); 0.441 vs 0.483 ms per query | `06_sqlite_duplicate_indexes.json` |
| Backfill trial (sandbox), 2026-03-02 → 03-27 | 74 trades, P&L 17,271.25 (= Day 3's level-3 window); **rerun replaced 74, inserted 74** (idempotent) | `07_backfill_sandbox_trial.log`, `07_backfill_sandbox_rerun.log` |
| **Backfill, main cloud** | 2026-03: 74 trades, 17,271.25 · 2025-11-03 → 12-16: 16 trades, −4,651.25 · together **90 rows, 12,620.00**; about 4 min each (run in parallel) | `08_*.log`, `09_*.log`, `backfill_main/` |
| Checks after the backfill | compat still 8 rows (min id 1); \|(exit − entry) × qty − P&L\| ≤ 0.50; audit: 90 INSERT + 90 UPDATE by `postgres` (backfill, then 0017's re-tag); **L1/L2 PASS 11/11** | `12_backfill_checks.txt`, `reconcile_l1_l2_after_backfill/` |
| **Strategy P&L (main cloud, `analyst`)** | backfilled backtest: 90 closed, 38 wins, 50 losses, **win rate 0.4222, total 12,620.00, max drawdown 7,783.75**; TIME_EXIT 13 trades +21,812.50, SL_HIT 77 trades −9,192.50; subcat `a` 80 trades −3,263.75, `g` 4 trades +15,953.75 | `10_analytics_main.md` |
| **Data quality (main cloud)** | missing 1m candles: 7 runs, 457 minutes, 6 days (longest 2025-10-21 09:15–13:44, 270 min); stale option snapshots on 2026-03-27: 3 gaps (62.5, 62.1, 56.2 min); VIX: 153 gaps over 10 min on 25 days, longest 256.5 min (2025-11-03, before the feed started) | `10_analytics_main.md` |
| Sandbox replay of 2026-03-27 as **`sync_writer`**, chaos `revise,rebuild,kill`, `sync once` every 30 steps | replay 385 s; first sync killed mid-batch (exit 75), 26 later syncs exit 0 (each took the lock); backlog 0; bot rebuild left 810 hourly candles | `replay_sandbox/01_replay.log` |
| … sync-lag view for that replay | 706 batches, 691,002 entries (345,892 upserts, 345,098 deletes, 0 rejected); latency p50 278.9 ms, p95 782.7 ms, max 2,338.9 ms; max lag 131.7 s; backlog at end 0 (run alongside the test suite, so slower) | `replay_sandbox/04_analytics_sandbox.md` |
| … reconciliation of the replayed sandbox | **L1 PASS, L2 PASS, L3 PASS** (2026-03-27: 2 trades, P&L 637.50 on both sides) | `replay_sandbox/reconcile/reconciliation.md` |
| Full suite | **57 tests, all pass, 308 s** (first run after slice 8: 57 pass, 308 s) | `13_test_suite.log`, `suite_run1.log` |
| **RDS** (`cloudsync-db`, PostgreSQL 17.11, ap-south-1, TLS 1.3): `migrate` | 17 migrations in 5.2 s; the master user (not a superuser) can act as all three roles with `-c role=` (no extra grant needed) | `artifacts/day4/rds/01_migrate.log` |
| RDS: `cdc-install` (fingerprints) + **bulk load** over the network | cdc-install 2.1 s (changelog backlog 0 before); bulk load **7 m 12 s**, same counts as Docker (`delta_cache` 348,109 read, 346,059 kept, 2,050 rejected; option_data 336,480) | `rds/02_cdc_install.log`, `rds/03_bulk_load.log` |
| RDS: backfill | 74 trades / 17,271.25 (4 m 35 s) and 16 / −4,651.25 (4 m 20 s), run in parallel | `rds/04_*.log`, `rds/05_*.log`, `rds/backfill/` |
| **RDS: reconciliation** | **L1 PASS 11/11, L2 PASS 11/11** (5.9 s); **L3 PASS** 2026-03-02 → 03-27: 74 trades, P&L 17,271.25 on both sides, 0 only-in-source, 0 only-in-cloud (5 m 58 s) | `rds/reconcile_l1_l2/`, `rds/reconcile_l3_2026-03/` |
| **After the switch** (`PG_DSN` = RDS, no `--dsn`) | `sync once` idle in 1.8 s (backlog 0, no daemon was running); **L1/L2 PASS 11/11** in 5.4 s | `rds/10_sync_once_default_dsn.log`, `rds/reconcile_after_switch/` |
| RDS: analytics as `analyst` | identical to the Docker main cloud (backfill 90 trades, 12,620.00, win rate 0.4222, max drawdown 7,783.75) | `rds/08_analytics_rds.md` |
| Real database after all Day-4 runs | SHA-256 `cf66a201…e0f1`, **matches** `artifacts/day2/rebuild/real_db_sha256.txt`; mtime 2026-06-16 20:43:10 (unchanged); no `-wal`/`-shm`/`-journal` | `00_real_db_sha256_before.txt`, `14_real_db_sha256_after.txt` |

## 4. Challenges and how they were fixed

### 4.1 A denied DELETE on a compat view failed for the wrong reason
- **Symptom:** the first roles test expected `InsufficientPrivilege` for
  `DELETE FROM dashboard_trade_history` as `bot_reader` and got "Views that do not select from
  a single table or view are not automatically updatable".
- **Root cause:** Postgres checks whether a view can be updated before it checks privileges.
  `compat.dashboard_trade_history` joins three tables, so the delete fails either way and
  proves nothing about the grant.
- **Fix:** the test deletes from `compat.dashboard_strategy_state`, a single-table
  (auto-updatable) view, where only the missing privilege can stop it. The base-table writes
  are tested too.
- **Verified:** the test passes, and the error class is `InsufficientPrivilege`.

### 4.2 Mutation checks, and a BOM that broke the first one
- Slices 2, 3, 6 and 7 first went red only because a role, relation or view was missing. So
  each one was mutation-checked: grant removed (sync fails with "permission denied for table
  schema_fingerprints"); WHEN guard removed (an extra no-op UPDATE audit row); run grouping
  collapsed (one run of 4 minutes instead of 3 + 1); backlog counted from the batch's first
  entry (3, 1, 0 becomes 4, 2, 0). Every mutant was killed, and the code was restored byte for byte.
- **Problem:** the first attempt rewrote the migration with PowerShell 5.1 `Set-Content
  -Encoding utf8`, which adds a BOM, so `migrate` failed with a syntax error. That run proved
  nothing. The BOM was stripped, and the later mutations ran through a small Python script
  that restores the original bytes.

### 4.3 Slice 5 passed on its first run
- The analyst/bot_reader boundary test needed no new code: the grants from slices 1–4 already
  held. It's kept as a regression guard on the boundary, and is recorded here as not
  test-driven.

### 4.4 The lock test hung instead of failing
- **Symptom:** the first red run of the lock test never finished.
- **Root cause:** without the lock, the second `sync daemon` simply runs forever, and the
  helper `run_cli` had no timeout.
- **Fix:** `run_cli(timeout=)` (the test helper only). The second daemon and the `sync once`
  run with 20 s, so a missing lock fails as `TimeoutExpired`. A cleanup of stray processes by
  name pattern was **blocked by the permission classifier**, rightly: it could have matched
  the owner's real sync daemon. Listing showed no strays left.
- **Verified:** red (`TimeoutExpired`), then green after the lock; the sandbox replay later
  showed a killed sync's lock being released (26 later syncs succeeded).

### 4.5 The bot already uses `source = 'backtest'`
- **Symptom:** after the first backfill, the P&L summary showed 92 "backtest" trades for
  `nifty-options` where 90 had been inserted, and a trading day in May 2026.
- **Root cause:** the dashboard's `DashboardStore.initialize()` seeds two demo trades with
  `source = 'backtest'` (+1,230.00). The tag chosen first wasn't unique.
- **Fix:** migration 0017 re-tags the backfilled rows `backtest-backfill` (the negative ids
  were already the hard boundary) and tightens the CHECK to `(id > 0) <> (source =
  'backtest-backfill')`.
- **Verified:** the summary now shows `backtest` 2 trades (1,230.00) and `backtest-backfill`
  90 trades (12,620.00 = 17,271.25 − 4,651.25); the audit log shows the 90 re-tag UPDATEs.

### 4.6 A relative work directory lost the backtest output
- **Symptom:** the first backfill trial ran the backtester for 2 minutes and then reported
  `FileNotFoundError: …\run_source_copy\trades.json`.
- **Root cause:** `parity.run_backtest` runs the worker with `cwd = run_dir` and passed it a
  relative output path, so the path resolved twice. Level 3 has the same trap with a relative
  `--parity-dir` (Day 3 used absolute temp dirs, so it never showed).
- **Fix:** `run_dir` is resolved to an absolute path in `run_backtest`.
- **Verified:** the trial rerun wrote 74 trades; the parity tests pass in the full suite.

### 4.7 The backtester's trade totals aren't dashboard prices
- **Finding:** `entry_price_total` is a signed net premium for the whole position (negative =
  paid), and the legs carry per-unit prices but no quantity. All 74 March trades are net-debit
  spreads (54 with 2 legs, 20 with 3), and for every one the total is exactly 50× the net leg
  premium.
- **Fix:** D62. The first mapping (side from the sign, qty 1) would have labelled every buy as a
  SELL. It was corrected before any main-cloud write.

### 4.8 The RDS wizard couldn't find Python, and saved an empty endpoint
- **Symptom:** the owner created `cloudsync-db` (ap-south-1, AZ ap-south-1b, automated backups
  7 days). Stage 5 of the wizard then said `.venv/Scripts/python: No such file or directory`
  and "Couldn't connect". `.env` had `RDS_HOST` empty (the region, user and a 12-character
  password were saved).
- **Root cause:** `bash` started from PowerShell is WSL's bash, where the Windows venv's
  interpreter is only reachable as `python.exe`. Separately, the endpoint prompt accepted an
  empty answer, so the test had no host to connect to anyway.
- **Fix:** the endpoint was written to `.env` by hand, and the connection test was run from the
  agent's shell (password read from `.env`, never printed). The wizard now `cd`s to the
  project root, prefers `.venv/Scripts/python.exe` (works from Git Bash and WSL), re-asks for
  an empty password, and only accepts an endpoint ending in `.rds.amazonaws.com`.
- **Verified:** connected in 0.51 s to **PostgreSQL 17.11 over TLS 1.3** as `cloudsync_admin`
  (not a superuser, has CREATEROLE), empty `algotrade` database; `RDS_PG_DSN` and
  `RDS_ADMIN_DSN` saved to `.env` (git-ignored) and both connect; `PG_DSN` still points at
  Docker. The wizard passes `bash -n` under Git Bash and WSL bash, and WSL runs the venv's
  `python.exe`.

## 5. Limitations and known gaps
| Limitation | Impact | Planned |
|---|---|---|
| The Docker main cloud is frozen as of the switch (D66) | It no longer follows the working copy; don't sync it from there again (that would prune entries RDS needs) | Keep for comparison, or drop later |
| `sandbox create` now clones on RDS by default (`--from-dsn` defaults to `PG_DSN`) | Experiments cost RDS storage/IO | Pass `--from-dsn "$DOCKER_PG_DSN"` for Docker sandboxes |
| The index audit and replay latencies were measured on Docker, not RDS | Network latency to RDS isn't in those numbers | Re-measure on RDS on Day 5 if time allows |
| Backfill has no automated test (D52) | A mapping regression only shows in a real run | Owner's choice; the runs are recorded and checked (section 3) |
| Trade history in the cloud ≠ SQLite by design (90 extra rows) | L1/L2 for that table compare `id > 0` only; a reader of the base table must filter on `source` | D61; the P&L views split by source |
| No index helps the `MAX(timestamp)` shapes (option ~400 ms, delta ~150 ms) or the full-range read | The bot's "latest snapshot time" query is slower on the cloud than in SQLite | Would need a view rewrite (e.g. MAX over the header table); report it as found |
| BRIN rejected on this data size (~90 MB, correlation 0.55 on candles) | — | Would be reconsidered for append-only, much larger tables |
| The duplicate `idx_` indexes stay in the bot's own database (D64) | 1.58 MB of duplicate pages in SQLite | Owner's call in the bot repo |
| The sync-lag views are empty on the main pair (no batch has ever been synced there) | Lag numbers come from the sandbox replay | Fills up as soon as the daemon runs on live data |
| Data-quality checks skip days a feed has no data at all | A day the option feed was completely down isn't flagged | D58; documented |
| The replay's latency numbers were measured while the test suite ran | p50/p95 somewhat high | Re-measure on RDS on Day 5 |
| Dead-tuple / autovacuum study (story 41) and bulk-load profiling not done | — | Out of today's scope (D53); story 41 is still open |

## 6. Open items carried forward
- [x] Owner created RDS `cloudsync-db` (ap-south-1, 7-day backups); connection verified, DSNs in `.env` (4.8).
- [x] RDS loaded: migrate, cdc-install, bulk-load, backfill (both windows), L1–L3 PASS (section 3).
- [x] RDS: role switching with `-c role=` works for the master user (no extra grant).
- [x] `PG_DSN` switched to RDS; verified through the default path: `sync once` idle, L1/L2 PASS (`rds/10_*`, `rds/reconcile_after_switch/`).
- [ ] **Day 5 first:** the PITR demo on RDS (the restore takes 10–20 minutes).
- [ ] Bot repo: commit or restore the uncommitted deleted result files on `main` (spec prerequisite).
- [ ] Owner: fix `BacktestableBot` (`_last_options_snapshot_timestamp`, Day 3 §4.4).
- [ ] Owner (new, optional): drop the duplicate `idx_market_data_{1m,5m,15m}_symbol_timestamp` in the bot's schema (D64).
- [ ] Story 41: dead tuples / autovacuum after the delete-heavy replay vs SQLite free pages.
- [ ] Profile the slower bulk load (Day 2 §5).
- [ ] Owner: optionally add a Claude Code permission deny rule for edits under `C:\Users\aryan\Desktop\AlgoTrade\db\`.
- [ ] Owner: register the Task Scheduler entry if wanted (`scripts\create_sync_task.bat`).
- [x] Day 4: sync-lag view; single-daemon advisory lock. Done (slices 7, 8).
- [x] Day 4: roles; `bot_reader` on `compat` only; `analyst` gets the `dq_*` views. Done (slices 1–6; the drift views are exposed as `analytics.dq_indicator_drift*`).
- [x] Day 4: index audit on the compat views' query shapes. Done (slices 9–11, D63).

## 7. How to reproduce
```bash
docker compose up -d
.venv/Scripts/python -m cloudsync migrate
.venv/Scripts/python -m cloudsync reconcile --sqlite data/trading_bot.db --levels 1,2 --out artifacts/day4/reconcile_l1_l2
.venv/Scripts/python -m cloudsync backfill-trades --sqlite data/trading_bot.db --start 2026-03-02 --end 2026-03-27 --out artifacts/day4/backfill_main
.venv/Scripts/python -m cloudsync backfill-trades --sqlite data/trading_bot.db --start 2025-11-03 --end 2025-12-16 --out artifacts/day4/backfill_main
.venv/Scripts/python scripts/analytics_report.py artifacts/day4/10_analytics_main.md
.venv/Scripts/python -m unittest discover -s tests -t .
```
Index audit, duplicate-index study and replay, **always in a sandbox** (D29):
```bash
.venv/Scripts/python -m cloudsync sandbox create day4
.venv/Scripts/python -m cloudsync bench-indexes --dsn "<sandbox dsn>" --out artifacts/day4/index_audit
.venv/Scripts/python scripts/sqlite_duplicate_indexes.py data/sandboxes/day4/trading_bot.db artifacts/day4/06_sqlite_duplicate_indexes.json
.venv/Scripts/python -m cloudsync replay --source data/trading_bot.db --target data/sandboxes/day4/trading_bot.db --day 2026-03-27 --chaos revise,rebuild,kill --sync-dsn "<sandbox dsn with options='-c role=sync_writer'>" --sync-every 30
.venv/Scripts/python -m cloudsync sandbox drop day4
```
RDS (owner, interactive): `bash scripts/rds_setup_wizard.sh` from the project root.

## 8. Demo / presentation notes
1. **Denied write:** connect with `options='-c role=bot_reader -c search_path=compat'`, run the
   dashboard's listing query (works), then `DELETE FROM dashboard_strategy_state` →
   `permission denied`. Then the same as `analyst` on `public.dashboard_trade_history`.
2. **Audit trail:** `SELECT table_name, op, actor, login, changed_at, old_row->>'source',
   new_row->>'source' FROM audit.audit_log ORDER BY audit_id DESC LIMIT 5` shows 0017's
   re-tag with old and new rows. Then show that `sync_writer` can't `DELETE FROM audit.audit_log`.
3. **Index audit:** `index_audit/index_audit.md`. The plain index on `ts` is useless here
   because the views filter on an expression; an expression B-tree takes 12.3 ms to 1.7 ms;
   BRIN is 50× smaller but slower for top-N. Then `06_sqlite_duplicate_indexes.json`: same
   plan, 1.58 MB of pure duplication in the bot's SQLite.
4. **Analytics:** `10_analytics_main.md`. P&L by source (window functions for the cumulative P&L
   and the running peak), the gaps-and-islands view of missing candles, the stale option chain.
5. **Sync lag:** `replay_sandbox/04_analytics_sandbox.md`, then the lock: start a daemon, run a
   second one → `REFUSED: another sync is already running…`.
6. **Honest finding:** the bot's dashboard seeds its demo trades as `source='backtest'` (4.5).
