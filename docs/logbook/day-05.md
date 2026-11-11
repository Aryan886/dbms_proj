# Day 5 — PITR on RDS, dead tuples, demo script and rehearsal (2026-11-09 → 11-10)

**Goal (from the spec's day plan):** PITR first (story 45: delete a day on purpose, restore RDS
to a moment before the delete, show the data back), then the report and the demo rehearsal.
The owner chose the rest of today's scope: the one-command demo (story 51), add-on labels
(story 52) and the dead-tuple study left over from Day 4 (story 41). The written report is
not part of today (D71).

**Outcome:** ✅ Done. **PITR PASS on RDS:** a deleted trading day (337,061 rows over 8 tables)
came back identical, by md5, on an instance restored to 23:40:00 IST. Dead tuples were measured
on RDS after a delete-heavy replay. A clock-skew bug in the sync-lag numbers, which only shows
on RDS, was found and fixed. The demo script ran end to end (**PASS in 16.9 min**, L1–L3 PASS after a killed sync). Full suite **59 tests, all pass**. Real database unchanged.

---

## 1. What was built

| # | Slice | Driving test | Main files |
|---|---|---|---|
| 1 | `pitr snapshot`: fingerprint of one IST day (row count + md5 of the sorted rows of each of the 8 day-scoped base tables, TimeZone UTC) plus the server clock | `test_a_deleted_day_is_reported_missing_and_a_pre_delete_copy_verifies` | `cloudsync/pitr.py`, `cli.py`, `tests/test_pitr.py` |
| 2 | `pitr delete-day`: deletes the day in one transaction (children before parents), records server time before and after; `pitr verify`: PASS/FAIL per table, exit 1 on FAIL | same test (a TEMPLATE copy taken before the delete stands in for the restored instance); mutation-checked (a `verify` that ignores the fingerprint makes it fail) | same |
| 3 | `delete-day` refuses `$PG_DSN` / `$DOCKER_PG_DSN` (REFUSED) | `test_delete_day_refuses_the_main_cloud_database` | same |
| 4 | PITR on RDS: sandbox on RDS, snapshot, delete, owner's console restore (guided in chat), verify | real run (needs the owner's AWS console) | `artifacts/day5/pitr/` |
| 5 | Dead-tuple study (story 41): samples of `pg_stat_user_tables` + autovacuum settings + SQLite `page_count`/`freelist_count`, before/after a delete-heavy chaos replay on an RDS sandbox and every minute for 15 min | measurement (spec: benchmarks aren't tests) | `scripts/dead_tuple_study.py`, `scripts/dead_tuple_run.sh` |
| 6 | Sync latency and lag measured on the sync process's clocks only (fix, 4.2) | existing sync/analytics tests (22 pass); **no new test**, the skew can't be reproduced on Docker; verified on RDS | `cloudsync/sync.py` |
| 7 | `scripts/demo.py`: the whole story in one command on its own demo pair, every measurement saved, add-ons labelled with evidence (stories 51–52) | rehearsal run (section 3) | `scripts/demo.py`, `artifacts/day5/demo_rehearsal/` |

**How the PITR demo works** (the explanation for the examiner): RDS keeps daily snapshots plus
the transaction log (WAL), shipped about every 5 minutes. A point-in-time restore creates a
**new instance** from the last snapshot and replays the log up to the second you choose. So the
live instance is never rolled back. We fingerprinted 2026-03-27 at 23:39:32 IST and deleted it at
23:40:40 IST. Restoring to 23:40:00 IST brings back the state between the two. `verify` then
compares the restored data with the fingerprint, table by table.

## 2. Decisions taken

| # | Decision | Owner | Alternatives considered | Why |
|---|---|---|---|---|
| D67 | PITR delete runs in a **sandbox database on the RDS instance**, not in the main cloud database | Team | Delete in the main RDS database | Keeps the main cloud pipeline-only (D29). A restore brings back the whole instance anyway, so the sandbox shows the same thing |
| D68 | The restore is done **by the owner in the RDS console, guided step by step in chat** (no AWS CLI or keys on this machine) | Team | A wizard script; install the AWS CLI | Owner's choice |
| D69 | Restored instance: Single-AZ, same VPC/subnet group/security group, public access, no deletion protection; **deleted right after verify** | Agent | Multi-AZ (the console's default) | A throwaway check; Multi-AZ doubles the cost and adds nothing to a PITR |
| D70 | PITR evidence = per-table count + md5 of the sorted rows of the day, compared on the restored instance, plus the live sandbox still damaged | Agent | Row counts only; reconcile against SQLite | md5 proves the rows are identical, not just as many; the damaged live copy proves the data came from the restore |
| D71 | Day-5 extra scope: demo script (51), add-on labels (52), dead tuples (41); **no report draft today** | Team | Also draft `docs/report.md` | Owner's choice |
| D72 | Dead-tuple study on an **RDS** sandbox (the replay also re-measures sync latency over the network) | Agent | Docker sandbox | Day-4 open item: latencies were Docker-only |
| D73 | Sync latency = the sync process's monotonic timer; lag = its wall clock minus `changed_at`; `started_at` = server commit time minus that latency | Agent | Keep server `clock_timestamp()` for both ends | RDS's clock is 1.49 s behind this machine; one clock per measurement removes the skew (4.2) |
| D74 | The demo uses its own pair (prep from the bot's database read-only, a fresh Postgres database on Docker by default), dropped afterwards unless `--keep` | Agent (implements D29) | Run on a `cloudsync sandbox` clone | Rehearses the whole story from the bot's database, including the VACUUM study and the bulk load |

## 3. Measurements (real runs only)

| Metric | Value | Artifact |
|---|---|---|
| RDS sandbox `algotrade_sbx_pitr`, fingerprint of 2026-03-27 at **18:09:32.80Z** | option_snapshots 336,480 · option_chain_snapshots 160 · delta_snapshots 6,355 · candles 482 · candle_indicators 482 · candle_sma 7 · vix_observations 91 · signals 4; **identical to the main cloud's** fingerprint (taken read-only) | `artifacts/day5/pitr/01_snapshot_sandbox.json`, `01_snapshot_main.json` |
| Deliberate delete | started **18:10:40.96Z**, committed 18:10:41.58Z, 337,061 rows (482 indicator rows by cascade), 2.1 s | `pitr/02_delete_day.json` |
| `verify` on the damaged sandbox | **FAIL**, all 8 tables at 0 rows | `pitr/03_verify_damaged_sandbox.log` |
| Restore (owner, console) | `cloudsync-db` → new instance `cloudsync-db-pitr`, restore time **2026-11-09 23:40:00 IST (18:10:00Z)**; console's latest restorable time was 23:43:39 IST, about 3 min after the delete | owner's console; chat |
| **`verify` on the restored instance** | **PASS**: sandbox db, all 8 tables identical (337,061 rows); main db, all 8 identical too; PostgreSQL 17.11 | `pitr/04_verify_restored_sandbox.log`, `05_verify_restored_main.log` |
| Control checks | live sandbox still **FAIL** after the restore; `algotrade_sbx_deadtup` (created 23:41 IST, after the target) **absent** on the restored instance, so the restore landed exactly at the chosen time | `pitr/06_*.log`, `07_restored_instance_facts.txt` |
| Chaos replay of 2026-03-27 on an **RDS** sandbox, `sync once` every 30 steps as `sync_writer` | replay + syncs **614 s** (Docker on Day 4: 385 s); 706 batches, 691,002 entries (345,892 upserts, 345,098 deletes, 0 rejected); final backlog 0 | `artifacts/day5/dead_tuples/replay.log`, `timing.txt`, `analytics_rds_sandbox.md` |
| **Dead tuples after the replay (story 41)** | 9,946 dead over 429,522 live (2.3 %) in the day-scoped tables; 25 autovacuums ran during the replay (option_snapshots 22, option_chain_snapshots 2, candle_sma 1); **unchanged for 15 min afterwards**: delta_snapshots 6,386 dead, candles 1,716, candle_indicators 1,716, vix 91 | `dead_tuples/dead_tuples.md`, `samples.jsonl` |
| Autovacuum settings on RDS | naptime 15 s, vacuum threshold 50 + 0.1 × reltuples, insert threshold 1000 + 0.2 × reltuples | same |
| **SQLite free pages after the same replay** | 0 → **303 free pages** (1.38 %), 21,623 → 21,899 pages, file 88.57 → 89.70 MB; unchanged for 15 min (SQLite reuses free pages but never shrinks without VACUUM) | same |
| Clock skew | RDS server clock **1,489 ms behind** this machine (RTT 19.6 ms); Docker 0.9 ms | `dead_tuples/clock_skew.txt` |
| Sync latency on RDS before / after the fix | before: p50 **−709 ms**, p95 72.9 ms (impossible values); after, 3 small batches: **251–268 ms**, `committed_at − started_at` equal to `latency_ms` | `analytics_rds_sandbox.md`, `latency_fix_check.txt` |
| Demo rehearsal | **PASS in 16.9 min** on its own Docker pair (dropped afterwards): prep 54.3 s, VACUUM 2,569,867,264 → 88,547,328 B (605,183 of 627,409 pages free, 96.46 %, VACUUM 8.5 s) · migrate 2.3 s · cdc-install 1.1 s · bulk load 427.7 s (delta_cache 2,050 rejected) · chaos replay + syncs 429.5 s · reconcile **L1 PASS 11/11, L2 PASS 11/11, L3 PASS** (2 trades, 637.50 on both sides), 83.2 s · roles: bot_reader reads 8 trades; its DELETE, analyst's base-table read and sync_writer's audit DELETE all **denied** · analytics as analyst 2.2 s · real DB SHA unchanged | `artifacts/day5/demo_rehearsal/summary.md` |
| Full suite | **59 tests, all pass, 284.6 s** (57 on Day 4 + 2 PITR tests) | `artifacts/day5/10_test_suite.log` |
| Real database | SHA-256 `cf66a201…e0f1` before; after all Day-5 runs: **identical**, mtime 2026-06-16 20:43:10 unchanged, no `-wal`/`-shm`/`-journal` | `artifacts/day5/00_real_db_sha256_before.txt`, `11_real_db_sha256_after.txt` |

## 4. Challenges and how they were fixed

### 4.1 RDS timed out at the start of the day
- **Symptom:** `psycopg` connection timeout to `cloudsync-db`; DNS resolved.
- **Root cause:** the home public IP had changed (now a mobile-range address), so the security
  group's "My IP" rule no longer matched. This is the case the Day-4 wizard warns about.
- **Fix:** the owner updated the inbound rule.
- **Verified:** TCP 5432 open, and every RDS step below connected.

### 4.2 Negative sync latency on RDS
- **Symptom:** the sync-lag view on the RDS replay sandbox showed latency p50 **−709 ms**.
- **Root cause:** each batch's `started_at` came from this machine's clock, while `committed_at`
  and the latency came from the server's `clock_timestamp()`. RDS's clock is **1.49 s behind**
  this machine's (measured: RTT-midpoint method, 7 tries). On Docker, the same machine, the skew
  is 0.9 ms, so the Day-4 numbers were right and no test could see it. The max lag had the same
  mix (SQLite's `changed_at` is local time, the server's clock was the other end).
- **Fix:** D73. Each measurement uses one clock: the sync process's monotonic timer for latency,
  its wall clock for lag (the same clock SQLite stamps with), and `started_at` derived from the
  server commit time minus that latency.
- **Verified:** sync and analytics tests pass (22). On RDS, new batches show 251–268 ms with
  `committed_at − started_at` = `latency_ms`. Old batches in that sandbox (≤ 706) still show
  the skewed values. **Limitation:** no automated test, because a skewed server clock can't be
  set up on the local Docker.

### 4.3 The PITR fingerprint first failed on `option_snapshots`
- **Symptom:** `column t.ts does not exist` in the first test run.
- **Root cause:** since the Day-1 header/line split (migration 0004), option lines have no
  timestamp; their day is their header's.
- **Fix:** each table has its own day predicate; option lines are selected through
  `option_chain_snapshots`.
- **Verified:** both PITR tests pass; on RDS the 336,480 lines are fingerprinted, deleted and
  restored.

### 4.4 The restore time field was in IST
- **Symptom:** the owner entered `18:10` (the UTC target) in a field labelled UTC+5:30.
- **Root cause:** the console shows local time; that would have restored to 12:40 UTC, before
  the sandbox existed.
- **Fix:** caught before submitting and corrected to 23:40:00 IST. For the demo: always read
  the time-zone label next to the field.

### 4.5 Dead tuples didn't go away
- **Finding (not a bug):** after the replay, 9,946 dead tuples stayed for 15 minutes. Autovacuum
  vacuums a table only when dead tuples exceed 50 + 10 % of `reltuples`. `option_snapshots` had
  336,480 deletes and was vacuumed 22 times during the replay. `delta_snapshots` (6,386 dead
  over about 346k rows) stays below its threshold of about 34.7k, so it waits. The `n_live_tup`
  counters start at 0 in a TEMPLATE clone, so the "before" sample isn't a live count;
  dead/deleted counts are exact because they started at 0 too.
- **What it shows:** Postgres leaves dead row versions (MVCC) for autovacuum to reclaim inside
  the table. SQLite deletes in place and keeps the pages on a freelist (303 here), which it
  reuses but only returns to the OS with VACUUM.

## 5. Limitations and known gaps

| Limitation | Impact | Planned |
|---|---|---|
| The latency/lag fix has no automated test (4.2) | A regression would only show on a server with a skewed clock | Documented; checked on RDS |
| Sync-lag rows written before the fix keep skewed values (RDS sandboxes are dropped; main RDS has no batches yet) | None on main | — |
| PITR restore needs the owner's AWS console (D68) | Not repeatable by script | Steps recorded in section 8 |
| The restored instance must be deleted by the owner | Costs credits while it exists | Owner asked to delete it (open item) |
| Demo defaults to Docker for its own cloud database | RDS network latency not in the demo timings | `--admin-dsn "$RDS_ADMIN_DSN"` runs it on RDS |
| Report draft not written (D71) | — | Day 6 (buffer) |

## 6. Open items carried forward
- [x] **PITR demo on RDS** (story 45). PASS (section 3).
- [x] Story 41: dead tuples / autovacuum vs SQLite free pages. Done on RDS (4.5).
- [x] Re-measure replay latency on RDS (Day 4). 614 s replay; latency fixed and re-checked (4.2).
- [x] Story 51 demo script and story 52 add-on labels. `scripts/demo.py`.
- [ ] **Owner: delete `cloudsync-db-pitr`** in the RDS console (no final snapshot).
- [ ] Report draft (`docs/report.md`) from the logbook and artifacts (D71: Day 6).
- [ ] Bot repo: commit or restore the uncommitted deleted result files on `main` (spec prerequisite).
- [ ] Owner: fix `BacktestableBot` (`_last_options_snapshot_timestamp`, Day 3 §4.4).
- [ ] Owner (optional): drop the duplicate `idx_market_data_{1m,5m,15m}_symbol_timestamp` in the bot's schema (D64).
- [ ] Profile the slower bulk load (Day 2 §5).
- [ ] Owner: optionally add a Claude Code permission deny rule for edits under `C:\Users\aryan\Desktop\AlgoTrade\db\`.
- [ ] Owner: register the Task Scheduler entry if wanted (`scripts\create_sync_task.bat`).
- [ ] Optional (spec): RDS read replica.

## 7. How to reproduce
```bash
docker compose up -d
.venv/Scripts/python -m unittest tests.test_pitr
# PITR, always on a sandbox (D67)
.venv/Scripts/python -m cloudsync sandbox create pitr
.venv/Scripts/python -m cloudsync pitr snapshot --dsn "<sandbox dsn>" --day 2026-03-27 --out artifacts/day5/pitr/01_snapshot_sandbox.json
.venv/Scripts/python -m cloudsync pitr delete-day --dsn "<sandbox dsn>" --day 2026-03-27 --out artifacts/day5/pitr/02_delete_day.json
#   owner: RDS console, restore cloudsync-db to a time between the two timestamps (section 8)
.venv/Scripts/python -m cloudsync pitr verify --dsn "<restored endpoint, same db>" --snapshot artifacts/day5/pitr/01_snapshot_sandbox.json
.venv/Scripts/python -m cloudsync sandbox drop pitr
# Story 41 on a sandbox
.venv/Scripts/python -m cloudsync sandbox create deadtup
bash scripts/dead_tuple_run.sh deadtup artifacts/day5/dead_tuples
.venv/Scripts/python -m cloudsync sandbox drop deadtup
# The whole demo (stories 51-52)
.venv/Scripts/python scripts/demo.py --out artifacts/day5/demo_rehearsal
```

## 8. Demo / presentation notes
1. **PITR (story 45):** show `pitr/01_snapshot_sandbox.json` (the server time), then
   `02_delete_day.json` (337,061 rows gone) and `03_verify_damaged_sandbox.log` (FAIL). In the
   console: cloudsync-db → Actions → Restore to point in time → Custom, **in the time zone the
   field shows** → Single-AZ, same VPC and security group, public access, no deletion
   protection. Then `04_verify_restored_sandbox.log` (PASS) beside `06_*` (live still FAIL).
   About 10–20 minutes, so show the recorded run unless there is time.
2. **Dead tuples (story 41):** `dead_tuples/dead_tuples.md`. 336k deletes in option_snapshots
   were vacuumed 22 times during the run; delta_snapshots keeps 6,386 dead tuples because it's
   under its 10 % threshold. SQLite: 303 free pages that stay until VACUUM.
3. **Honest finding:** negative latency on RDS, caused by clock skew (4.2). Good for explaining
   why distributed measurements need one clock.
4. **Whole story in one command:** `scripts/demo.py`, then open its `summary.md`. The add-on table
   is story 52.
