# Day 2 — WAL, CDC triggers, sync engine, drift handling (2026-11-06)

**Goal (from the spec's day plan):** switch the working copy to WAL; capture every insert,
update and delete with generated triggers; build the sync engine (`once` and `daemon`) with
exactly-once effect, crash recovery and offline back-off; pause a table on schema drift until a
migration and resume. Also: the WAL concurrency benchmark (story 19) and the Windows start-up
mechanism (story 28).

**Outcome:** ✅ Done. CDC is installed on the real 88 MB working copy. The bot's own
delete-and-rebuild of `market_data_1h` (2,045 changes) synced in 3 batches, and
**L1 + L2 reconciliation still PASS for all 10 tables**. A 1,000-change batch commits in about
160 ms. With WAL, the bot's write latency under a concurrent sync reader dropped from
**p50 1,203 ms to 0.98 ms**. The suite now has 33 end-to-end tests, all passing.
**Follow-up the same day:** an experiment had changed the main working copy's 1h data (4.4).
The cross-check explained every missing row, the main pair was rebuilt from the real database
and proven identical to it, and a write guard plus throwaway sandboxes now keep it from
happening again (D28–D32).

---

## 1. What was built

| # | Slice | Driving test | Main files |
|---|---|---|---|
| 1 | Tracer bullet: WAL + `_changelog` + generated triggers + `sync once` + prune + `sync_state` | `test_insert_after_cdc_install_reaches_postgres_and_changelog_is_pruned` | `cloudsync/cdc.py`, `cloudsync/sync.py`, `migrations/0005_sync_bookkeeping.sql` |
| 2 | Revisions (`ON CONFLICT DO UPDATE`: same id, new values) | `test_revised_candle_is_reflected_in_the_cloud` | — |
| 3 | Bot's delete-and-rebuild of 1h candles (all ids change) | `test_delete_and_rebuild_of_hourly_candles_reaches_the_cloud` | `tables.py` (`delete_sql`, `natural_key`) |
| 4 | `INSERT OR REPLACE` (vix) + plain DELETE (signal) | `test_insert_or_replace_vix_and_deleted_signal_propagate` | — |
| 5 | Batching (~1000, configurable) + `sync_batches` log | `test_many_changes_sync_in_batches` | `sync.py` |
| 6 | Kill mid-batch → rerun: no duplicates, no gaps | `test_crash_mid_batch_then_rerun_leaves_no_duplicates_or_gaps` | `sync.py` (`CLOUDSYNC_FAULT`) |
| 7 | Kill after commit, before prune → harmless | `test_crash_after_commit_before_prune_is_harmless` | `sync.py` |
| 8 | Postgres unreachable → retries with back-off → later catches up | `test_postgres_unreachable_then_available_catches_up` | `sync.py` (`once`) |
| 9 | Daemon: backs off while the link is down, resumes when it returns, keeps up | `test_daemon_backs_off_while_offline_and_resumes_when_the_network_returns` | `sync.py` (`daemon`), `tests/support.py` (`TcpForwarder`) |
| 10 | A quarantined row is released when the bot corrects it (Day-1 open item) | `test_quarantined_candle_is_released_when_the_bot_corrects_it` | `sync.py` |
| 11 | `delta_cache` duplicates via CDC; deleting the survivor promotes its sibling | `test_delta_duplicates_via_cdc_and_deleting_the_survivor_promotes_its_sibling` | `0005` (`delete_delta_cache`) |
| 12 | An observed option row corrects a contract derived earlier from a trade (Day-1 open item) | `test_observed_option_row_corrects_a_contract_derived_from_an_earlier_trade` | `0005` (`upsert_observed_contract`) |
| 13 | Schema drift: only that table pauses; resume refused until a migration | `test_added_column_pauses_only_that_table_until_a_migration_and_resume` | `sync.py` (`_check_drift`, `drift_resume`), `migrate.py` (`--extra-dir`) |
| 14 | WAL vs rollback-journal benchmark | `test_benchmark_reports_both_journal_modes_and_leaves_the_source_untouched` (smoke only; the spec says benchmarks are measurements) | `cloudsync/bench.py` |
| 15 | Batched deletes (after the real run showed 3 s/batch) | existing suite + real re-run | `sync.py` (`_apply_deletes`) |
| 16 | Windows start-up: `.bat` + Task Scheduler registration | manual smoke (log line below) | `scripts/start_sync_daemon.bat`, `scripts/create_sync_task.bat` |
| — | Real run on the working copy | manual; artifacts below | `artifacts/day2/` |
| 17 | *(owner follow-up)* Cross-check of the rebuilt 1h table against the real database | read-only script; `14_1h_crosscheck.txt` | — |
| 18 | *(owner follow-up)* Working copy + cloud rebuilt from the real database; row-for-row proof | read-only script; `rebuild/09_rowcompare_vs_real_db.txt` | `prep.py` (side-file cleanup), `test_re_prep_discards_a_stale_wal_left_by_the_previous_working_copy` |
| 19 | *(owner follow-up)* Write guard: the real database and the bot repository are read-only to cloudsync | `test_commands_that_write_sqlite_refuse_the_real_database`, `test_read_only_commands_still_work_on_the_real_database` | `cloudsync/guard.py` |
| 20 | *(owner follow-up)* Throwaway sandboxes for every experiment | `test_sandbox_experiment_leaves_the_main_working_copy_and_cloud_untouched` | `cloudsync/sandbox.py` |

**CLI added today:** `cdc-install`, `sync once`, `sync daemon`, `drift-resume`, `bench-wal`, and
`migrate --extra-dir` (see the [project README](../../README.md)).

**How one sync pass works** (the explanation to give the examiner):
1. **Drift check.** Each table's live column list (`PRAGMA table_info`) is hashed and
   compared with the fingerprint stored at install. On a mismatch that table is paused and
   logged; the others carry on.
2. **Prune** changelog entries that Postgres already acknowledged. This covers a crash
   between a commit and its prune.
3. **Batches** of about 1,000 entries, taken after each active table's `sync_state.last_seq`:
   - The entries **and the rows they point at** are read in one SQLite read transaction. In
     WAL mode that's a consistent snapshot that never blocks the bot.
   - Entries are collapsed per (table, pk), and the row's **current** state is applied: many
     updates become one upsert, and a missing row becomes a delete.
   - All deletes, upserts and rejects, the `sync_state` moves and the `sync_batches` row
     commit in **one** Postgres transaction.
   - Only after that commit are the entries pruned from SQLite.

## 2. Decisions taken

| # | Decision | Owner | Alternatives considered | Why |
|---|---|---|---|---|
| D13 | Triggers record only (table, pk, op, seq); the sync reads the row's current state at apply time | Spec | Store the full row image in the changelog | The spec's design. Updates collapse, replays are idempotent, and the changelog stays small |
| D14 | `_changelog.seq` is `AUTOINCREMENT` | Agent | Plain `INTEGER PRIMARY KEY` | A plain rowid restarts at 1 once the table is pruned empty, so new changes would sort below `last_seq` and be **skipped silently** |
| D15 | One cursor per source table in `sync_state`, and the batch query skips paused tables | Spec + Agent | One global cursor | A global cursor can't move past a paused table's entries without losing them |
| D16 | Tables keyed by a natural key in the cloud (candles, option lines, deltas) have the cloud image of each changed source row **deleted before it is re-applied**. Tables keyed by source pk use a plain upsert | Agent | Upsert only | A changed id, or an id that moved to another natural key, can't leave a stale row or a `source_id` clash. Plain upsert keeps the PK-keyed tables FK-safe (strategies ← trades) |
| D17 | The rejects of every touched row are re-decided each batch (cleared, then re-applied) | Agent | Clear only on success | Closes the Day-1 gap; a row that is still bad is quarantined again in the same transaction |
| D18 | Deleting the surviving `delta_cache` row promotes the highest quarantined sibling | Agent (extends D10) | Leave the key empty | "Highest **remaining** id wins" keeps holding after deletes |
| D19 | An observation beats a derivation: an observed row corrects a derived contract's key (or merges into the existing contract and re-points its trades), and an observed tradingsymbol replaces a derived one | Agent | Quarantine the option row | Closes the Day-1 gap. Kite monthly symbols carry no expiry day, so holiday shifts are real |
| D20 | Fingerprints live in Postgres (`schema_fingerprints`). They are written at `cdc-install` and **never overwritten by a re-install**. Resume needs `max(schema_version)` > the version when paused | Agent (implements Spec) | Store them in SQLite; resume on demand | Overwriting would silently accept drift. The version check makes "resume requires a migration" enforceable |
| D21 | Fault injection through `CLOUDSYNC_FAULT=mid_batch:N` or `after_commit:N` (`os._exit`, like kill -9) | Agent | Kill the process from the test on a timer | Deterministic. The Day-3 chaos toggle can reuse it |
| D22 | `once` retries with exponential back-off (3 retries by default) and then fails with the changelog intact. `daemon` retries forever (0.5 s doubling, 30 s cap) | Agent | `once` fails at once | Tests and demos can show back-off without a daemon |
| D23 | The benchmark uses two **processes**, the bot's busy timeout (Python's default, 5 s) plus a 0.5 s run, and the reader scans `delta_cache` in a read transaction | Agent | Threads | Threads would measure Python's GIL, not SQLite locking |
| D24 | The real-data run exercises deletes with the **bot's own** `backfill_market_data_1h` on the working copy | Agent | A synthetic delete script | A real code path on real data. Side effect: see 4.4 |
| D25 | Deletes are pipelined with `executemany`, falling back row by row only on failure | Agent | One savepoint per row | Measured about 19× faster (3.0 s → 0.16 s per 1,000-change batch) |
| D26 | The daemon starts from `scripts/start_sync_daemon.bat`; `create_sync_task.bat` registers it daily at 09:10 (the bot starts at 09:15) | Agent (implements Spec) | A Windows service | Same mechanism as the bot's own `start_live_data.bat` and `create_tasks.bat` |
| D27 | `migrate --extra-dir` adds a directory of numbered migrations; duplicate version numbers are refused | Agent | Copy files into the package | Drift fixes (and the test) can ship a migration without editing the package |
| D28 | **The bot's real database is read-only: only read actions are allowed on it** | Team | — | Owner's rule after 4.4. Enforced by `cloudsync/guard.py` and written into `CLAUDE.md` |
| D29 | **Every experiment runs on a throwaway sandbox**, never on the main working copy or the main cloud database | Team | — | Owner's rule after 4.4. `cloudsync sandbox create/drop` makes it a one-liner |
| D30 | The guard protects the `SOURCE_DB` file **and everything under `BOT_REPO`**, and it's checked inside each writing function, not only in the CLI | Agent (implements D28) | Protect just the one file | A stray path into the bot repo (for example a benchmark output dir) would be just as bad |
| D31 | A sandbox is a matched pair: a backup-API copy of the working copy, plus a `CREATE DATABASE … TEMPLATE` clone of the cloud database | Agent (implements D29) | A SQLite copy only | Syncing a sandbox must not touch the main cloud database, and CDC state, `sync_state` and fingerprints must match the copy |
| D32 | The main pair was rebuilt from the real database (prep, then a fresh `algotrade` with migrate, cdc-install, bulk-load). The Day-2 rebuild results are kept as historical artifacts | Team (asked) + Agent (method) | Undo only the 1h table | A full rebuild plus a row-for-row comparison proves the whole pair, not just one table |

## 3. Measurements (real runs only)

| Metric | Value | Artifact |
|---|---|---|
| Baseline before CDC (Day-1 load still matches) | L1 + L2 PASS, 10/10 | `artifacts/day2/00_baseline/reconciliation.md` |
| `cdc-install` on the 88 MB working copy | 0.87 s wall; journal mode `delete` → `wal`; 10 tables × 3 triggers | `artifacts/day2/02_cdc_install.log` |
| Idle `sync once` | 0 entries, 0.83 s wall (mostly process start-up) | `artifacts/day2/03_sync_idle.log` |
| Bot's 1h delete-and-rebuild, run 1 | 1,235 D + 810 I = **2,045 changes** captured | `artifacts/day2/04_backfill_1h.log` |
| Sync of run 1 (deletes one per round trip) | 3 batches, 7.1 s wall; batch latency 2,966 / 3,082 / 188 ms | `05_sync_rebuild.log`, `07_sync_batches.txt` |
| Bot's 1h rebuild, run 2 | 810 D + 810 I = 1,620 changes | `08_backfill_1h_again.log` |
| Sync of run 2 (batched deletes, D25) | 2 batches, **1.18 s wall**; batch latency **161.6 / 157.5 ms** | `09_sync_rebuild_batched_deletes.log`, `07_sync_batches.txt` |
| Reconciliation after each real sync | **L1 PASS 10/10, L2 PASS 10/10** | `artifacts/day2/reconciliation.md`, `06_reconcile.log`, `10_reconcile.log` |
| Writer with a concurrent reader, busy timeout 5 s, 10 s per mode | rollback journal: **16** writes, p50 **1,203 ms**, max 1,330 ms. WAL: **1,569** writes, p50 **0.98 ms**, p99 1.87 ms | `artifacts/day2/wal_benchmark.md` |
| Same, busy timeout 0.5 s | rollback journal: 14 OK, **10 lock errors**. WAL: 1,566 OK, **0 errors** | `artifacts/day2/bench_timeout_0.5s/wal_benchmark.md` |
| Reader scan of `delta_cache` (346k rows) | p50 ≈ 1.2 s in both modes, 0 read errors | same files |
| Daemon via the `.bat` | log line `sync daemon started: data\trading_bot.db (batch 1000, poll 1.0s)` | `logs/sync_daemon.log` (gitignored) |
| Test suite | **29 tests, all pass, 146 s** (174 s wall including start-up) | `artifacts/day2/13_test_suite.log` |
| **Follow-up:** real database unchanged | SHA-256 `cf66a201…e0f1`, mtime 2026-06-16 20:43 (before the project began), 2,569,867,264 bytes, no `-wal`/`-shm`/`-journal` files | `artifacts/day2/rebuild/real_db_sha256.txt`, `sandbox_rebuild_demo/06_real_db_sha256_after.txt` |
| 1h cross-check: rebuilt vs original | 810 hours in both with **identical OHLC**; **425** hours only in the original; 0 new hours | `artifacts/day2/14_1h_crosscheck.txt` |
| … the 425 missing hours | **350** on 50 days that have no 15m data at all; **74** were the 15:15 closing bar (one 15m candle, not four); **1** was 2025-10-21 13:45 (Muhurat session) | same |
| … indicator values on the 810 common hours | AO/Donchian empty in the original but filled by the rebuild: 41; AO/Donchian different: 403; SL/SH different: 325 | same |
| Rebuild: `prep` from the real database | 2,569,867,264 → 88,547,328 bytes, 605,183 free pages → 0; VACUUM 5.2 s; 1 m 9 s total | `artifacts/day2/rebuild/prep_stats.json`, `01_prep.log` |
| Rebuild: bulk load into a fresh `algotrade` | 5 m 17 s (Day 1: 2 m 8 s; see 5) | `rebuild/05_bulk_load.log` |
| Rebuild: reconciliation | **L1 + L2 PASS 10/10 against the working copy, and again with the real database itself as the source** (opened read-only); `market_data_1h` back to 1,235 | `rebuild/reconcile_vs_working_copy/`, `rebuild/reconcile_vs_real_db/` |
| Rebuild: row-for-row, working copy vs real database | **All 24 tables identical** (both directions of `EXCEPT`, all columns); only extra table: `_changelog` | `rebuild/09_rowcompare_vs_real_db.txt` |
| Sandbox replay of the bot's 1h rebuild | 2,045 changes (1,235 D + 810 I) in 3 batches, sandbox L1/L2 PASS; main working copy SHA-256 and main cloud's 1,235 hourly rows unchanged | `artifacts/day2/sandbox_rebuild_demo/` |
| Test suite after the safety work | **33 tests, all pass, 177 s** | `artifacts/day2/15_test_suite_after_safety.log` |

**What the benchmark shows.** In rollback-journal mode a writer needs an EXCLUSIVE lock to
commit, so it waits for every reader's SHARED lock. The bot's write stalls for the whole sync
scan (≈1.2 s). With a short busy timeout it fails outright ("database is locked"). In WAL mode
the reader works from a snapshot (the main file plus the WAL), while the writer appends to the
WAL, so neither waits.

## 4. Challenges and how they were fixed

### 4.1 Deletes were 20× slower than upserts on real data
- **Symptom:** in the first real run, each 1,000-change batch took about 3 s. Upserts were
  fast; the delete-heavy batches weren't.
- **Root cause:** each delete ran in its own savepoint and round trip. Upserts already used
  pipelined `executemany`, with a per-row fallback only on failure.
- **Fix:** gave deletes the same pattern (D25).
- **Verified:** re-ran the bot's rebuild on real data. Batch latency fell to 161.6 / 157.5 ms,
  and reconciliation still passes (`07_sync_batches.txt`, `10_reconcile.log`).

### 4.2 `INSERT OR REPLACE` doesn't fire DELETE triggers
- **Finding (design, from the SQLite docs):** rows that REPLACE removes don't fire DELETE
  triggers unless `recursive_triggers` is on. The bot uses REPLACE for `vix_data`.
- **Why it's safe here:** the replacing row has the same pk, so its INSERT entry re-applies
  the cloud row under that key.
- **Verified:** `test_insert_or_replace_vix_and_deleted_signal_propagate`.
- **Worth presenting:** a real trigger gotcha, and why the changelog stores keys, not images.

### 4.3 Process deviation: the core engine came before most tests had been seen failing
- **What happened:** after the tracer-bullet test went red → green, the general engine
  (collapse per pk, delete-before-reapply, rejects re-decided, drift check) already made
  slices 2–13 pass on their first run. They weren't seen failing first.
- **Mitigation:** each of those tests was **mutation-checked**. The code it guards was broken
  on purpose, the test was run (it failed every time) and the code was restored:
  - the UPDATE trigger disabled → revision and REPLACE tests fail;
  - deletes skipped → delete test fails;
  - reject re-decision removed → correction test fails;
  - sibling promotion disabled → promotion test fails;
  - derived-contract correction disabled → correction test fails;
  - drift check disabled → drift test fails.
- **Lesson:** the next slices (Day 3) go back to strict one-red-test-at-a-time.

### 4.4 The bot's 1h rebuild changed the working copy's data
- **Finding:** `backfill_market_data_1h` rebuilt 1h from 15m and produced **810 rows where
  there were 1,235**. The working copy's 1h table no longer matches the original source.
- **Status at the time:** the cloud matched the working copy (L1/L2 PASS), which is the
  sync's job, but the working copy no longer matched the real database.
- **Root cause (an agent process error):** the experiment ran on the **main** working copy
  instead of a throwaway copy.
- **Where the 425 rows went** (read-only cross-check, `14_1h_crosscheck.txt`). The bot's
  resampler keeps an hour only when it has all four 15-minute candles (`counts == 4` in
  `resample_15m_to_1h`):
  - **350 hours** sit on **50 days with no 15m data at all** (10–21 Nov 2025 and 26 Dec 2025 –
    20 Feb 2026). The original 1h rows for those days came from somewhere else, so they
    can't be rebuilt from 15m.
  - **74 hours** were the **15:15 closing bar**. It contains a single 15m candle
    (15:15–15:30), so it is never "complete".
  - **1 hour** was 2025-10-21 13:45, the Muhurat session. Its four 15m candles straddle two
    09:15-aligned hours.
  - The 810 surviving hours have identical OHLC, but **many indicator values changed**
    (403 AO/Donchian, 325 SL/SH). The rebuild isn't neutral for the strategy either.
- **Fix:** the whole main pair was rebuilt from the real database (D32). It was proven
  identical row for row (all 24 tables), and reconciliation passes with the real database as
  the source.
- **Prevention:** D28/D29. A code guard (`guard.py`) refuses writes to the real database and
  the bot repository, every experiment runs in a sandbox, and the rule is in `CLAUDE.md`. The
  same rebuild was replayed in a sandbox to show the main pair stays put.
- **Finding worth reporting about the bot itself:** running `backfill_market_data_1h` in
  production would silently delete 425 hourly candles and change the indicators the strategy
  reads.

### 4.6 A stale WAL file next to a fresh working copy (checked, not a real risk)
- **Concern:** `prep` deleted the old copy's main file but not the `-wal`/`-shm` files left
  by WAL mode. Could SQLite replay those old frames into the new copy?
- **Check:** a regression test leaves a WAL holding uncheckpointed deletes, re-runs `prep`,
  then switches the new copy to WAL. **It passed even without a fix:** SQLite discarded the
  old WAL when the fresh file was first opened (observed, not assumed). No red test drove the
  change.
- **Change anyway:** `prep` now removes `-wal`, `-shm` and `-journal` along with the old copy,
  so no stale file is left beside a new one.

### 4.5 Smaller issues
- **Windows line endings:** Python text-mode rewrites turned LF files into CRLF.
  Normalized back to LF; `git diff` stays clean.
- **A suite run left no summary:** the first full run, started in the background, wrote
  only part of its log, with no "Ran N tests" line, so it doesn't count as evidence. It was
  re-run in the foreground: 29/29 OK (`13_test_suite.log`).
- **`.env.example`:** a `printf` turned `\t` (in `data\trading_bot.db`) into a tab. Repaired.
- **`executescript` gotcha (avoided):** Python's `executescript` COMMITs any open transaction
  first, so the changelog DDL runs as separate `execute` calls inside `BEGIN IMMEDIATE`.

## 5. Limitations and known gaps

| Limitation | Impact | Planned |
|---|---|---|
| After a drift resume, a **new** source column isn't synced: the mapping in `tables.py` lists columns explicitly | The rest of the row syncs, and the drift was recorded with a migration | Mapping a new column is a code change per drift; document it in the report |
| A delete that Postgres refuses (for example a strategy deleted while the cloud still holds its trades) is recorded in `rejected_rows` as `_op: delete` | L1 would flag that table, so it's detected, not hidden | Not seen in the bot's write paths |
| `INSERT OR REPLACE` on a table with **two** unique keys could remove a row under a different pk without a trigger | Stale cloud row | The bot only uses REPLACE on `vix_data` (one key); keep it documented |
| Nothing stops two daemons from running at once | Replays are idempotent, but it's untested | Day 4: `pg_try_advisory_lock` guard (small) |
| `sync_batches.max_lag_ms` measures from the SQLite capture time, so it includes the time the bot's own script took | Overstates lag for bulk scripts | Day 4 sync-lag view: show latency and lag separately |
| Benchmarks ran on one laptop with a local disk | Absolute numbers are machine-specific; the ratio is the point | Note in the report |
| `option_data` duplicates on (snapshot, contract) are overwritten (Day 1) | Shown as an L1 mismatch, so detected | Still open; 0 in real data |
| Running on local Docker, not RDS | Connection-string change only | Day 4 |
| The guard covers `cloudsync` commands only. **Bot functions called directly aren't guarded**, and their default `db_path` is the relative `db/trading_bot.db` | A call without an explicit `db_path` from inside the bot repo would hit the real database | Rule in `CLAUDE.md`: always pass an explicit sandbox path; a Claude Code permission deny rule is offered to the owner |
| Bulk load is now 5 m 17 s, against 2 m 8 s on Day 1 | Slower baseline loads; it doesn't affect incremental sync | Day 4: profile. The likely cause (not verified) is that `upsert_observed_contract` became plpgsql in 0005 and runs for each of about 684k option/delta rows |
| A sandbox needs the daemon stopped (template clone) | Creating one fails while something is connected to `algotrade` | Documented in `sandbox.py` |

## 6. Open items carried forward
- [ ] Bot repo: commit or restore the uncommitted deleted result files on `main` (still
  present on 2026-11-06; spec prerequisite).
- [x] Day 1: "fingerprints must use production's column order". Closed: fingerprints are
  taken from the live `PRAGMA table_info` of the database CDC is installed on.
- [x] Day 1: derived → observed contract reconciliation. Closed by D19 (slice 12).
- [x] Day 1: clear a reject when its source row is corrected. Closed by D17 (slice 10).
- [x] Choose the level-3 parity baseline after 4.4. Closed: the main pair was rebuilt from the
  real database and proven identical (D32), so Day 3 compares against the real data.
- [ ] Day 3: every chaos/replay run happens in a `cloudsync sandbox` (D29).
- [ ] Day 4: profile the slower bulk load (see 5).
- [ ] Owner: optionally add a Claude Code permission deny rule for edits under
  `C:\Users\aryan\Desktop\AlgoTrade\db\` (the agent didn't change settings).
- [ ] Day 3: the chaos toggles reuse `CLOUDSYNC_FAULT` (kill mid-batch) and the bot's real
  delete-and-rebuild.
- [ ] Day 4: sync-lag view over `sync_batches`, `sync_state`, the `_changelog` backlog and
  `rejected_rows`; single-daemon advisory lock.
- [ ] Owner: register the Task Scheduler entry if wanted. Run
  `scripts\create_sync_task.bat` as Administrator. The agent didn't, because it changes
  system configuration.

## 7. How to reproduce
```bash
docker compose up -d
.venv/Scripts/python -m cloudsync migrate
.venv/Scripts/python -m cloudsync cdc-install --sqlite data/trading_bot.db
.venv/Scripts/python -m cloudsync sync once --sqlite data/trading_bot.db
.venv/Scripts/python -m cloudsync reconcile --sqlite data/trading_bot.db --levels 1,2 --out artifacts/day2
.venv/Scripts/python -m cloudsync bench-wal --sqlite data/trading_bot.db --out artifacts/day2 --seconds 10
.venv/Scripts/python -m unittest discover -s tests -t .
```
To repeat the real delete-and-rebuild, **always in a sandbox** (D29):
```bash
.venv/Scripts/python -m cloudsync sandbox create rebuild1h      # prints its sqlite path and dsn
# run the bot's utils.market_data_1h.backfill_market_data_1h(db_path=<sandbox sqlite>)
.venv/Scripts/python -m cloudsync sync once --sqlite <sandbox sqlite> --dsn "<sandbox dsn>"
.venv/Scripts/python -m cloudsync reconcile --sqlite <sandbox sqlite> --dsn "<sandbox dsn>" --levels 1,2 --out <dir>
.venv/Scripts/python -m cloudsync sandbox drop rebuild1h
```
The commands used for the rebuild of the main pair are in `artifacts/day2/rebuild/` (logs
numbered in order).

## 8. Demo / presentation notes
1. **WAL in one table:** `artifacts/day2/wal_benchmark.md`. 16 vs 1,569 writes in 10 s, and
   p50 1.2 s vs 1 ms. Then the 0.5 s-timeout run, where the rollback journal throws
   "database is locked" 10 times.
2. **CDC live:** run `sqlite3 data/trading_bot.db ".schema _changelog"` and show a generated
   trigger. Write one candle with the bot, show the `_changelog` row, run `sync once`, and
   show the row in Postgres and the changelog empty.
3. **Exactly-once:** run
   `CLOUDSYNC_FAULT=mid_batch:2 cloudsync sync once --batch-size 4`, which exits 75. Show that
   Postgres holds exactly batch 1, rerun, and reconcile PASSes. Then do the same with
   `after_commit:1`: the rerun applies nothing and only prunes.
4. **Why AUTOINCREMENT matters** (D14): a one-line answer to "what if the changelog is pruned
   to empty?".
5. **Drift:** `ALTER TABLE signals ADD COLUMN …`. Sync logs `SCHEMA DRIFT: signals`, the other
   tables keep moving, `drift-resume` is refused, then a migration is applied and the table
   resumes. `schema_version` records it.
6. **Real data:** the bot's own 1h rebuild produced 2,045 changes, synced in about 1 s, and
   L1/L2 PASS. Run it in a sandbox.
7. **Safety story:** show the guard refusing `cdc-install` on the real database (`REFUSED`)
   and `rebuild/09_rowcompare_vs_real_db.txt` (24/24 identical). Be honest about 4.4: the
   mistake, the cross-check that explained every one of the 425 rows, and the guard and
   sandbox that came out of it.
