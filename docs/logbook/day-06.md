# Day 6 — Presenter script for the examiner demo (2026-11-17)

**Goal (from the spec's day plan):** Day 6 was the buffer day, and Day 5 moved the report
draft to it (D71). The owner took Day 6's planned scope (buffer and report draft) **out of
scope** (D76) and asked for one thing only: a script to run and present the demo properly.

**Outcome:** ✅ Done. `scripts/present.py` builds the demo pair once (`prepare`, 17.7 min),
then walks the examiner through 9 segments, live on that pair (`live`, about 30 s of
commands when run unattended; the rest is talking). Every check passed on the final run, L3
included (2 trades, P&L 637.50 on both sides). On the way we found that the **bot's real
database lost all of its `vix_data` rows on 2026-11-11**, outside this project (4.2).

---

## 1. What was built

| # | Slice | Driving test | Main files |
|---|---|---|---|
| 1 | `present.py prepare`: runs `demo.py --keep` and prints the `live` command | real run (section 3) | `scripts/present.py` |
| 2 | `present.py live`: 9 segments, each with its syllabus topic, "SAY" talking points and live actions on the kept pair; `--only` to rehearse one segment, `--auto` for an unattended check; full log saved under `<run>/live/` | real unattended run, every check PASS (section 3) | `scripts/present.py` |
| 3 | Live segments: CHECK violation straight into Postgres; a bad candle written in SQLite gets quarantined by the sync, then leaves the quarantine once it's corrected; trigger → `_changelog` → `sync once`; a crash mid-batch (`CLOUDSYNC_FAULT=mid_batch:1`) leaves the cloud and its cursor unchanged, then a restart applies the change once; role denials; EXPLAIN ANALYZE with and without the IST expression index (the index is dropped inside a rolled-back transaction); a 3 s WAL benchmark; L1–L2 reconcile; SHA check | same run | same |
| 4 | Recorded segments: VACUUM study, PITR on RDS (Day 5), L3 from `prepare`, the clock-skew finding | same run | same |
| 5 | `present.py cleanup`: drops the demo database and working copy, keeps the artifacts | used on the failed pair (4.2) | same |
| 6 | `demo.py --source`: the database to copy and replay from (read-only); step 9 still hashes the bot's real database | real run (section 3) | `scripts/demo.py` |
| 7 | Guide verification handbook: the commands a guide may ask us to run live (constraints, transactions, joins, views, roles, audit trigger, EXPLAIN, MVCC, locking, SQLite WAL/triggers, CDC, quarantine, crash test, reconcile, WAL benchmark, tests), each with expected output and viva Q&A; three terminals (PowerShell, psql in Docker, sqlite3) on a `viva` sandbox | every command run once on a sandbox (section 3) | `docs/viva/guide_verification_commands.docx`, generator `docs/viva/make_guide.js` |

No new automated tests: both scripts are presentation drivers over CLI commands that the
suite already covers. They were verified by real runs. The suite was re-run after the
`demo.py` change (section 3).

## 2. Decisions taken

| # | Decision | Owner (Team/Agent/Spec) | Alternatives considered | Why |
|---|---|---|---|---|
| D75 | The demo is built from the **main working copy** `data/trading_bot.db` (read-only), not the bot's database | Team | Owner restores the bot DB from a backup; present with L3 FAIL | The bot DB's `vix_data` is empty since 2026-11-11 (4.2), so the backtest refuses to run; the working copy still has the original data |
| D76 | Day 6's planned scope (buffer, report draft) is out of scope; only the demo script is done | Team | Draft `docs/report.md` | Owner's choice |
| D77 | Demo = `prepare` beforehand + `live` in the room: slow steps (VACUUM, 8-min bulk load, PITR restore) shown from artifacts, quick steps run live | Agent | Run `demo.py` live (17.7 min) | A live bulk load is dead time; live steps still show real behaviour |
| D78 | Index segment drops `candles_ist_ts` inside a transaction that's rolled back | Agent | A second database without the index | One query, before and after, on the same data; it also shows that DDL is transactional |
| D79 | Segment 1 shows the Day-5 VACUUM numbers when the demo source is already vacuumed | Agent | Show the 0-free-page numbers from the working copy | The story is about the bot's 2.5 GB file; the numbers are labelled with their artifact |
| D80 | Guide handbook: commands run on our laptop, local Docker only (RDS/PITR shown from artifacts); covers live DBMS commands, `cloudsync` runs and viva Q&A | Team | Fresh clone on the guide's PC; include RDS commands; add code-ownership checks | Owner's answers to the scoping questions |
| D81 | Handbook sandbox is cloned from the Docker main pair (`--from-dsn .../algotrade` + `data/trading_bot.db`), not the kept demo pair | Agent | Clone the demo pair `20261117-1435` | Demo pair is dropped after the presentation and was left with a bad candle (4.5); the Docker pair reconciled L1–L2 PASS |
| D82 | SQL in the handbook is typed in interactive `psql` (`docker compose exec`) and `sqlite3` shells, `cloudsync` in PowerShell | Agent | Everything as PowerShell one-liners | No PowerShell quoting of `"timestamp"`; the guide can type their own SQL |

## 3. Measurements (real runs only)

| Metric | Value | Artifact |
|---|---|---|
| `prepare` from the bot's DB (first try) | **FAIL** in 17.7 min: L1 11/11, L2 11/11 PASS; L3 FAIL on both sides (`BacktestDataCoverageError`: vix_data "no data") | `artifacts/demo/20261117-1405_failed_l3_vix_empty/summary.md` |
| `prepare` from the working copy | **PASS** in 17.7 min: bulk load 525.2 s, chaos replay 423.2 s, reconcile L1–L3 93.7 s | `artifacts/demo/20261117-1435/summary.md` |
| L3 backtest parity | PASS: 2 trades, P&L 637.50 on source and cloud, 0 differences | `artifacts/demo/20261117-1435/06_reconcile/reconciliation.md` |
| `live --auto`, all 9 segments | every check PASS; 0.5 min unattended | `artifacts/demo/20261117-1435/live/present_20261117-145325.log` |
| Expression index, latest-200 candles | 2.60 ms with the index, 21.99 ms without it (seq scan on candles) | `artifacts/demo/20261117-1435/live/present_20261117-145325.log` |
| WAL benchmark, 3 s per mode | delete mode 2 writes (p50 1,419 ms); WAL 446 writes (p50 1.09 ms) | `artifacts/demo/20261117-1435/live/bench_wal/wal_benchmark.md` |
| Bot DB SHA-256 | `a5b0a381…` before and after every run today; **differs** from the Day-2 reference `cf66a201…` (4.2) | `artifacts/day6/real_db_sha256.txt` |
| Working copy SHA-256 | `1d5fbf0e…` before and after the run that read it | this log (sha256sum) |
| Test suite | 59 tests in 304.4 s: **56 pass, 3 errors**, all `AttributeError: module 'utils' has no attribute 'vix_fetcher'` (4.4) | `artifacts/day6/test_suite.log` |
| Handbook sandbox (Docker main pair) | `sandbox create` ~5 s; reconcile L1–L2 PASS in ~3 s; an edited cloud candle makes L2 FAIL on 1 of 88 days (exit 1), re-sync makes it PASS | expected-output boxes in `docs/viva/guide_verification_commands.docx` |
| Handbook index check | latest-200 query 3.99 ms with `candles_ist_ts`, 28.59 ms without (seq scan) | same |
| Handbook WAL benchmark, 3 s | delete mode 5 writes (p50 1,096 ms); WAL 375 writes (p50 1.16 ms) | same |
| `tests.test_roles` + `tests.test_safety` | 6 tests in 34.9 s, OK | same |
| Bot DB SHA-256 after the handbook runs | `a5b0a381…`, equal to the Day-6 baseline | `artifacts/day6/real_db_sha256.txt` |

## 4. Challenges and how they were fixed

### 4.1 `scripts/demo.py` "missing"
- **Symptom:** the session started on `main`, and `scripts/demo.py` wasn't there.
- **Root cause:** local `main` was 2 commits behind `origin/main`, where PR #3 (Day 5) had
  been merged.
- **Fix:** fast-forwarded `main` to `origin/main`, then branched `day6_demo_runbook`.
- **Verified:** `scripts/demo.py` and `tests/test_pitr.py` present; log shows `bddec88`.

### 4.2 The bot's database lost its VIX data
- **Symptom:** the first `prepare` failed at L3. The bot's backtester raised
  `BacktestDataCoverageError` ("vix_data … Available: no data") on **both** sides, so the
  comparison had nothing to compare.
- **Root cause:** the bot's real `trading_bot.db` has **0 rows** in `vix_data` (2,885 on Day 5).
  The file was last modified **2026-11-11 15:07 IST**, and its SHA-256 no longer matches the
  Day-2 reference. That happened outside this project: the hash was already `a5b0a381…` when
  today's run started, and the run left it unchanged. The bot repo got four commits on 10–11 Nov,
  including changes to `utils/vix_fetcher.py` and `utils/db_setup.py`. The cause inside the
  bot wasn't investigated (bot repo is read-only for this project).
- **Fix:** owner's decision D75: build the demo from the main working copy, which still has all
  2,885 VIX rows (91 for 2026-03-27). `demo.py` and `present.py prepare` gained `--source`.
- **Verified:** the second `prepare` passed L1–L3; the working copy's hash is unchanged.

### 4.3 Bugs in the first draft of `present.py`
- **Symptom:** the PITR snapshot time printed `?`; the WAL step dumped raw JSON; key=value
  DSNs could have printed a password.
- **Root cause:** wrong JSON key (`server_time`); `lines[-0:]` is the whole list; the first
  scrub regex only handled URL-style DSNs.
- **Fix:** right key; `tail=0` prints nothing; `scrub()` handles both DSN styles, and the
  displayed commands show `"<demo dsn>"` and relative paths instead.
- **Verified:** re-run of segments 3, 6, 7 and 8, then the full unattended run.

### 4.4 Three tests now error after the bot's 10–11 Nov changes (open)
- **Symptom:** `test_delta_cache_duplicates_keep_highest_id_and_quarantine_the_rest`,
  `test_delta_snapshots_load_and_reconcile` and
  `test_latest_option_and_delta_snapshot_queries_return_the_same_rows_from_the_cloud` fail at
  `patch("utils.vix_fetcher.fetch_live_option_chain")` with
  `AttributeError: module 'utils' has no attribute 'vix_fetcher'`. All 59 passed on Day 5.
- **Root cause (partial):** `patch` couldn't import `utils.vix_fetcher` in the test process.
  The module imports fine on its own, and `fetch_live_option_chain` still exists, so it's an
  import-time failure under the tests' setup. It started with the bot's commits `9dbc6c0` and
  `15ea2d8`, which changed `utils/vix_fetcher.py`. Today's files aren't involved: no test
  imports `scripts/`.
- **Fix:** not done today (open item).
- **Verified:** n/a.

### 4.5 The kept demo pair was left with a bad candle (fixed)
- **Symptom:** while preparing the handbook, the demo pair's SQLite
  (`data/demo/20261117_1435/trading_bot.db`) had candle `28148126` with close 22878.45 above
  its high 22828.45, and one unsynced `_changelog` entry; the cloud still had 22824.7.
- **Root cause:** the 15:23 rehearsal (`live/present_20261117-152301.log`) stopped after
  segment 3 wrote the bad close, before the sync and the correction ran. On the next `live`,
  segment 3 reads that bad close as the "original" and restores it, so its PASS check fails.
- **Fix:** with the owner's approval, set the close back to 22824.7 in the demo SQLite and ran
  `sync once` to the demo database as `sync_writer` (2 entries, 1 upsert, 0 rejected).
- **Verified:** cloud close 22824.7, `_changelog` empty, 0 `market_data_1m` rejects; then
  `present.py live --only 3,4 --auto` passed every check and left both candles at their
  original values (`artifacts/demo/20261117-1435/live/present_20261117-232134.log`).

## 5. Limitations and known gaps

| Limitation | Impact | Planned |
|---|---|---|
| The demo's data comes from the working copy (D75), not the bot's current database | The demo shows the data as of Day 1–5; fine for the course, but say so if asked | Owner decides whether to restore the bot DB |
| The bot's database no longer matches the Day-2 reference hash | The "real DB unchanged" check now compares against the hash before each run | Owner: restore or re-baseline the reference (open item) |
| `present.py` has no automated test | A regression would show at rehearsal, not in CI | Rehearse with `live --auto` before presenting |
| PITR and the VACUUM study are shown from recorded artifacts | Not live | By design (D77) |
| Report draft not written (D76) | — | Out of scope |
| Handbook numbers come from the Docker main pair as of 2026-11-17 | Row counts may drift if the working copy changes; error messages and plans won't | Re-run section 2.5 before the check |
| Handbook was not rendered in LibreOffice; checked through Word (24 pages) and the docx schema validator | — | none |

## 6. Open items carried forward
- [ ] **Owner: find out why the bot's `trading_bot.db` lost its `vix_data` on 2026-11-11**, and
      restore it from a backup if that wasn't intended. Then either re-baseline
      `artifacts/day2/rebuild/real_db_sha256.txt` or go back to the original file.
- [ ] Fix the 3 tests that error after the bot's `vix_fetcher` changes (4.4).
- [ ] Owner: delete `cloudsync-db-pitr` in the RDS console (from Day 5; not confirmed done).
- [ ] Owner: run `present.py cleanup` after the presentation (the demo pair `20261117-1435` is kept).
- [x] ~~Repair the demo pair's bad candle before the next `present.py live`~~ (4.5, done).
- [ ] Team: rehearse the guide handbook once (`docs/viva/guide_verification_commands.docx`), each member owning a few checks.
- [x] ~~Report draft (`docs/report.md`)~~: out of scope (D76).
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
.venv/Scripts/python scripts/present.py prepare            # ~18 min, before the presentation
.venv/Scripts/python scripts/present.py live --auto        # rehearsal check, every line PASS
.venv/Scripts/python scripts/present.py live               # in the room: Enter between steps
.venv/Scripts/python scripts/present.py live --only 3,4    # rehearse one member's segments
.venv/Scripts/python scripts/present.py cleanup            # afterwards
```

## 8. Demo / presentation notes

| # | Segment | Topic | Live or recorded | ~min |
|---|---|---|---|---|
| 1 | The problem | storage internals, VACUUM | recorded (Day 5) | 2 |
| 2 | Normalized schema | ER, FDs, 3NF, keys (open `docs/normalization.md`) | live counts and FKs | 3 |
| 3 | Constraints and quarantine | CHECK, rejected_rows | live | 3 |
| 4 | Change capture and crash safety | triggers, atomicity, recovery | live | 4 |
| 5 | Least privilege | roles, GRANT | live | 1 |
| 6 | Indexing and concurrency | expression index, EXPLAIN, WAL | live | 3 |
| 7 | PITR on RDS | backup and recovery | recorded (Day 5) | 2 |
| 8 | Proof | L1–L2 live, L3 from `prepare`, SHA | live + recorded | 2 |
| 9 | Honest finding | clock skew | recorded | 1 |

If asked where the data comes from: the demo pair is a copy of the working copy made on Day 1
from the bot's database. The bot's own file changed on 2026-11-11 (4.2).
