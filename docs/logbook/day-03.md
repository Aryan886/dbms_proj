# Day 3 — Compatibility & indicator views, replay simulator, level-3 parity (2026-11-07)

**Goal (from the spec's day plan):** Postgres views named and shaped exactly like the bot's
SQLite tables (story 14); SMA/AO/Donchian computed in SQL with window functions and a
data-quality view of the drift against the stored values (stories 15–17); a replay simulator
with chaos toggles (36–39); level-3 parity: export the views to SQLite, run the unchanged
backtester on both and diff the trades (34).

**Outcome:** ✅ Done. The bot's real queries return the same rows from Postgres (`compat`
schema, 11 views). **Level 3 passes on the main pair in both windows the backtester can complete:
Nov 3 – Dec 16, 2025 (16 trades, P&L −4,651.25) and March 2026 (74 trades, P&L 17,271.25),
identical trade for trade.** The full range can't be shown, because the bot's backtester stops at
2025-12-17 on the source data itself (4.5). A replayed day with all three chaos toggles passes
L1–L3 in a sandbox. Two findings about the bot came out of it: the spec's "never-read" SMA
table is read (4.2, so it's now migrated), and the bot's backtester crashes on any open
position (4.4, so level 3 runs it with an owner-approved shim).

---

## 1. What was built

| # | Slice | Driving test | Main files |
|---|---|---|---|
| 1 | Tracer bullet: `compat.market_data_1m`, checked with the bot's own `fetch_market_data` query | `test_latest_candles_query_returns_the_same_rows_from_the_cloud` | `migrations/0006_compat_views.sql`, `tests/test_compat_views.py` |
| 1a | Test fixture gets production's column order for 1m/5m/15m (found by slice 1, see 4.1) | same test | `tests/support.py` |
| 2 | `compat.market_data_5m/15m/1h` (1h has its own column order) | `test_backtester_range_query_matches_for_every_timeframe` | `0006` |
| 3 | `compat.vix_data`, `compat.signals` | `test_vix_and_signal_queries_return_the_same_rows_from_the_cloud` | `0006` |
| 4 | `compat.dashboard_strategy_state`, `compat.dashboard_trade_history` (dashboard's own listing queries) | `test_dashboard_listing_queries_return_the_same_rows_from_the_cloud` | `0006` |
| 5 | `compat.option_data` (header + line + contract), `compat.delta_cache` (latest-snapshot queries) | `test_latest_option_and_delta_snapshot_queries_return_the_same_rows_from_the_cloud` | `0006` |
| 6 | `market_sma_1h` becomes the 11th in-scope table: `candle_sma` + `compat.market_sma_1h` (see 4.2, D33) | `test_backtester_hourly_sma_query_matches` | `migrations/0007_hourly_sma.sql`, `tables.py` |
| 7 | CDC for a composite source key `(timestamp, symbol)`: triggers record `timestamp\|symbol` | `test_hourly_smas_with_a_composite_key_follow_rebuilds_replaces_and_deletes` (mutation-checked, see 4.3) | `cdc.py`, `tables.py`, `reconcile.py` |
| 8 | `candle_indicators_computed`: SMA 5/20/50/200, SMA of highs/lows, AO, Donchian(20) with named `WINDOW` frames | `test_window_function_indicators_match_the_hand_worked_series` (expected values worked by hand) | `migrations/0008_indicator_views.sql`, `tests/test_indicator_views.py` |
| 9 | `dq_indicator_drift` + `dq_indicator_drift_summary`: stored vs computed, per candle and indicator | `test_drift_view_flags_stored_values_that_restarted_after_a_gap` (drift counts worked by hand) | `migrations/0009_indicator_drift_views.sql` |
| 10 | Level 3: export `compat` → fresh SQLite (source DDL), export fidelity, unchanged backtester on both, trade diff | `test_backtest_on_the_cloud_export_makes_the_same_trades` | `cloudsync/parity.py`, `cloudsync/_backtest_worker.py`, `reconcile.py`, `tests/test_parity.py` |
| 10a | Backtester shim for the bot's own crash (4.4, D42) | same test (the window trades, so it needs the shim) | `_backtest_worker.py` |
| 11 | A cloud copy that lost data fails level 3, and a backtest that refuses to run is reported, not raised (4.5) | `test_a_cloud_copy_missing_option_deltas_fails_and_names_the_lost_trades` | `parity.py`, `reconcile.py` |
| 12 | Replay simulator: rewind a day, replay it in time order through the bot's writers; chaos `revise`, `rebuild`, `kill`; optional `sync once` every N steps | **no automated test (D35)**; recorded sandbox run (section 3), refusal of the real DB in `test_commands_that_write_sqlite_refuse_the_real_database` | `cloudsync/replay.py`, `cli.py` |
| 13 | `bulk-load --tables` (load the new table into the main cloud without re-loading 730k rows) | manual, real run (`03_bulk_load_market_sma_1h.log`) | `bulk_load.py`, `cli.py` |
| — | Real runs: main pair to Day 3 (migrate, CDC, load), L1/L2, drift, L3 windows; replay in a sandbox | manual; artifacts below | `artifacts/day3/` |

**How level 3 works** (the explanation to give the examiner):
1. **Export.** Each `compat` view is written into a fresh SQLite file. Its tables are created
   from the source's own DDL (`sqlite_master`), so the column order, the affinities and the
   indexes are the bot's. Rows go in in source-key order with the same ids.
2. **Export fidelity** (informational). Each exported table is compared with its source table,
   row for row, with `EXCEPT` in both directions. Any expected difference (the quarantined
   `delta_cache` duplicates) shows up here and names the table behind a trade difference.
3. **Two backtests.** The bot's backtester runs on a backup copy of the source and on the
   export, each in its own `python -I` process in a scratch directory. Bot code never touches
   the source file.
4. **Trade diff.** Trades are paired by (entry time, lot, position type). Every field is
   compared (legs, prices, SL history, exit reason) except `trade_id`, a random `uuid4`.
   Level 3 passes when nothing is only on one side or different, and both runs completed.

**How the compatibility views work** (the explanation to give the examiner): they live in a
separate schema, `compat`, with one view per source table. Each view has the same name, the
same column names in the same order (surrogate ids included) and the same value types the bot
gets back from SQLite: IST wall-clock `timestamp`, and `double precision` for prices. A client
whose `search_path` is `compat` runs the bot's SQL unchanged; only the driver's placeholder
(`?` vs `%s`) differs. Each test runs the bot's **real** query text (copied from
`utils/db_func.py`, `backtesting/data_provider.py` and `server/dashboard_store.py`) against
SQLite and against Postgres, and compares column names, column order and every row.

## 2. Decisions taken

| # | Decision | Owner | Alternatives considered | Why |
|---|---|---|---|---|
| D33 | **`market_sma_1h` is migrated as stored data** (11th in-scope table, `candle_sma`), changing spec story 13 | Team | Leave it out and explain the diff; serve SQL-computed SMAs | The backtester reads it and the strategy uses 1h sma_20/50/200; the stored values can't be recomputed (4.2), so storing them is the only way to exact parity |
| D34 | Replay: candles, VIX and signals go through the bot's write functions; `option_data`/`delta_cache` rows of the day are inserted verbatim (triggers still fire) | Team | Fake clock + fake Kite through the bot's option/delta writers; skip options | The bot's option writer stamps `datetime.now()` and the delta writer calls Kite and recomputes deltas, which would change the day's data |
| D35 | Day-3 test seams: compatibility views, indicator + drift views, `reconcile --levels 3`. **The replay simulator is checked by a recorded sandbox run, not an automated test** | Team | Also test replay + chaos | The owner's choice of seams |
| D36 | The level-3 test uses a slice of the working copy (opened read-only) that is known to produce trades | Team | Synthetic bot-written data | Synthetic candles would most likely trade zero times, and "both trade lists are empty" proves nothing |
| D37 | Compatibility views live in their own schema `compat`; consumers set `search_path = compat` | Agent | Views in `public` with renamed base tables | `signals` and `dashboard_*` base tables already carry the source names |
| D38 | View types: `timestamp` (IST wall clock, without time zone, independent of the session time zone) and `float8` for every price | Agent | Text timestamps (byte-identical to SQLite) | Typed values keep `timestamp >= '…'` working with real comparison semantics, and the bot can pass datetimes. Text would hide the typing gain |
| D39 | View column order follows **production**, not the bot's `create_tables()` | Agent (implements Spec) | Follow `create_tables()` | The spec says "exact column names and order of the original SQLite tables"; they differ (4.1) |
| D40 | A composite source key is recorded in `_changelog` as one text value, the key columns joined by `\|` | Agent | Record SQLite's `rowid` | `rowid` of a table without an INTEGER PRIMARY KEY can change on VACUUM; the natural key can't |
| D41 | `candle_sma` has **no FK** to `candles` | Agent | FK on (instrument, timeframe, ts) | The bot writes and deletes SMA rows independently of candles; a FK would make sync depend on write order. The data-quality view reports orphans instead |
| D42 | **Backtester shim:** the parity worker sets a class-level default for the attribute the bot's backtester is missing (4.4), on both runs | Team | Owner fixes the bot first; report the crash with no trade comparison | Keeps every bot file unchanged, and the comparison fair |
| D43 | Each backtest runs in its own process (`python -I`, cwd = scratch) on a **copy**: a backup-API copy of the source, and the export | Agent | Run both in-process; run on the source file | The backtester opens its database read-write (`CREATE TABLE IF NOT EXISTS`), and its module-level state must not leak between the two runs |
| D44 | The export creates each table from the **source's own DDL** (`sqlite_master`), then fills it from the compat view in source-key order | Agent | The bot's `create_tables()` | Same column order, affinities and indexes as the database being compared (4.1). Same ids, so the same physical order |
| D45 | Level 3 also reports **export fidelity**: each exported table vs its source table, row for row (`EXCEPT` both ways). Informational, not part of pass/fail | Agent | Only diff trades | When trades differ, the table that caused it is visible straight away |
| D46 | A backtest that refuses or crashes is a **level-3 result** (FAIL, with its last error line), not a crash of `reconcile` | Agent | Let the exception propagate | A cloud copy that lost data makes the backtester refuse the window; that's exactly what level 3 must report (4.5) |
| D47 | Real level-3 runs use windows the backtester can complete: 2025-11-03 → 2025-12-16 and 2026-03-02 → 2026-03-27. The full-range run is kept as evidence | Agent | Only the full range | The full range stops on 2025-12-17 **on the source itself** (4.5), so it can't show trade parity |
| D48 | `bulk-load --tables` loads a subset of source tables | Agent | Re-run the whole bulk load | The new table needed 1,235 rows; the other 730k were already proven by L1/L2 |
| D49 | Replay targets must have CDC installed and are refused if they are the real database (guard) or the main working copy | Agent (implements D29) | Trust the operator | The replay rewinds a day with DELETEs: never on the main pair |

## 3. Measurements (real runs only)
| Metric | Value | Artifact |
|---|---|---|
| Stored `market_sma_1h` vs a window-function SMA over `market_data_1h` (first look, in SQLite) | matching rows out of 1,235: sma_5 1,223 · sma_20 1,202 · sma_50 1,172 · **sma_200 1,022**; max abs difference sma_200 242.8, sma_20 272.9 | read-only query on `data/trading_bot.db`; the same numbers from Postgres are in `06_indicator_drift_summary.md` |
| Main pair brought to Day 3 | `migrate` applied 6–9 in 1.1 s; `cdc-install` 1.3 s (11 tables, `market_sma_1h` key `timestamp\|symbol`); `bulk-load --tables market_sma_1h` 1,235 read / 1,235 kept / 0 rejected in 1.3 s; `sync once` idle | `artifacts/day3/01`–`04_*.log` |
| Reconciliation, main pair, 11 tables | **L1 PASS 11/11, L2 PASS 11/11** (`delta_cache` 348,109 = 346,059 + 2,050 rejected) | `artifacts/day3/reconcile_l1_l2/reconciliation.md` |
| Indicator drift on real data (`dq_indicator_drift_summary`, 6.6 s) | AO/Donchian: **every drifted row is a stored NULL** (stored_missing = rows_drifted; max diff 0.0000 where both exist), e.g. 1m AO 1,320 of 32,543, 15m AO 1,588 of 3,379. 1h SMAs differ in value: sma_200 213 rows (max 242.77), sma_50 63 (427.22), sma_20 33 (272.92), sma_5 12 (124.33) | `artifacts/day3/06_indicator_drift_summary.md` |
| Level 3, main pair, full range 2025-11-03 → 2026-03-27 | **FAIL**: both runs stop at 2025-12-17 14:22:44 with the same `StrictBacktestDataError` (4.5); 6 m 44 s; export fidelity 10/11 identical, `delta_cache` differs by exactly the 2,050 quarantined duplicates | `artifacts/day3/reconcile_l3_main/`, `07_reconcile_l3_main.log` |
| **Level 3, main pair, 2026-03-02 → 2026-03-27** | **PASS: 74 trades on both sides, 0 only-in-source, 0 only-in-cloud, 0 changed; P&L 17,271.25 on both.** Shim applied (D42). 4 m 24 s (both backtests side by side). Export fidelity 10/11 identical; `delta_cache` short by exactly the 2,050 quarantined duplicates | `artifacts/day3/reconcile_l3_main_2026-03/`, `08_reconcile_l3_main_2026-03.log` |
| **Level 3, main pair, 2025-11-03 → 2025-12-16** | **PASS: 16 trades on both sides, 0 only-in-source, 0 only-in-cloud, 0 changed; P&L −4,651.25 on both.** Shim applied (D42). 5 m 0 s | `artifacts/day3/reconcile_l3_main_2025-11_12/`, `09_reconcile_l3_main_2025-11_12.log` |
| Replay of 2026-03-27 in sandbox `replay0327`, chaos `revise,rebuild,kill`, `sync once` every 30 steps | rewound 343,450 rows; re-wrote 375 1m / 75 5m / 25 15m / 7 1h candles, 7 SMA, 91 VIX, 4 signals, 336,480 option and 6,386 delta rows; **12 candles revised**; bot rebuild left 810 hourly candles; **first sync killed mid-batch (exit 75)**, 26 later syncs exit 0; backlog 0; 7 m 20 s | `artifacts/day3/replay_sandbox/02_replay_summary.json` |
| … what the sandbox cloud committed | 706 batches, 691,002 changes (345,892 upserts, 345,098 deletes, 0 rejected); batch latency p50 395 ms, max 2,452 ms | `replay_sandbox/05_sandbox_sync_batches.txt` |
| … reconciliation of the replayed sandbox | **L1 PASS, L2 PASS, L3 PASS** (2026-03-27: 2 trades on both sides, P&L 637.50 on both) | `replay_sandbox/reconcile/reconciliation.md` |
| … main pair after the replay | main working copy SHA-256 unchanged (`f772c929…1261` before and after); main cloud still 1,235 hourly candles and SMAs, 0 `sync_batches` | `replay_sandbox/00_*.txt`, `04_main_pair_after_replay.txt` |
| Real database after all Day-3 runs | SHA-256 `cf66a201…e0f1`, **matches** `artifacts/day2/rebuild/real_db_sha256.txt`; mtime 2026-06-16 20:43:10 (unchanged); no `-wal`/`-shm`/`-journal` | `artifacts/day3/00_real_db_sha256_before.txt`, `11_real_db_sha256_after.txt` |
| Backtester on a throwaway copy, 2026-03-02 → 03-27, with the shim | 74 trades, P&L 17,271.25, about 5 minutes (file times) | scratch probe (the same window's level-3 report is below) |
| Full suite after the fixture change | 34 tests, all pass, 198 s | scratch run |
| **Full suite, end of day** | **44 tests, all pass, 295 s** (run alongside the last level-3 window, so slower) | `artifacts/day3/10_test_suite.log` |

## 4. Challenges and how they were fixed

### 4.1 The bot's `create_tables()` doesn't produce production's column order
- **Symptom:** the first compatibility test failed only on column order:
  `…, donchian_mid, SL, SH, vix_value` (view) vs `…, donchian_mid, vix_value, SL, SH` (fixture).
- **Root cause:** in production, `market_data_1m/5m/15m` got `SL`, `SH` (no declared type) and
  then `vix_value REAL` by `ALTER TABLE`. Today's `create_tables()` declares all three inline,
  in a different order. `market_data_1h` was created later and does match `create_tables()`.
- **Fix:** the views follow production (D39). `make_bot_db` rebuilds the three empty tables the
  way production got them (base columns, then the three `ADD COLUMN`s), the same kind of
  additive fix it already applied to `delta_cache`.
- **Verified:** the test passes; the full suite (34) still passes; the fixture's
  `PRAGMA table_info` now equals the working copy's for all ten Day-2 tables.

### 4.2 The spec's "never-read" SMA tables are read by the backtester
- **Finding:** `HistoricalDataProvider._merge_with_sma_1h` merges `market_sma_1h` into the 1h
  candles. `_compute_required_indicators` only computes `sma_20/50/200` when they're missing,
  so the stored values win. `main_category_a_active` and sub-categories l/n/o read them.
- **Could SQL recompute them?** No (measured, section 3). The stored series restart after data
  gaps (for example 2025-09-25 09:15: stored sma_20 25,031.7, a 20-row window gives 25,176.2).
- **Decision:** the owner chose to migrate it as stored data (D33).

### 4.3 Slice 7 passed on its first run
- **What happened:** slice 6 already needed composite-key triggers, otherwise `cdc-install`
  would refuse the new table and break the whole sync suite. So the sync test for that path
  went green on its first run.
- **Mitigation:** mutation-checked. Shifting the delete key by one hour, and recording only the
  first key column in the trigger, each made the test fail. The code was restored after each.

### 4.4 The bot's own backtester crashes on any run that holds a position
- **Symptom:** the first full-range probe (2025-09-10 → 2026-03-27, on a throwaway copy) and a
  four-week probe (March 2026) both died with
  `AttributeError: 'BacktestableBot' object has no attribute '_last_options_snapshot_timestamp'`,
  raised from `runner._run_trading_day → BacktestableBot.get_unrealized_pnl →
  NiftyBot._resolve_leg_current_price` (`core/bot_nifty.py:543`).
- **Root cause (in the bot, not in cloudsync):** bot commit `0e2b6b7` (2026-04-29) added
  `self._last_options_snapshot_timestamp` to NiftyBot's mark-to-market log lines.
  `BacktestableBot` never sets that attribute, so the first 5-minute equity update with an open
  position crashes, whichever database the backtester reads. With the committed code, no
  backtest that holds a position can finish, on either side of the comparison.
- **Fix (owner's choice, D42):** cloudsync's backtest worker gives `BacktestableBot` a
  class-level default `_last_options_snapshot_timestamp = None` before each run. No bot file
  changes; the value only feeds a log line; the same shim applies to both runs, so the
  comparison stays fair. The level-3 report states that the shim was applied.
- **For the owner:** the real fix belongs in the bot repository (initialise the attribute in
  `BacktestableBot.__init__`).
- **Verified:** with the shim, the four-week window completes with 74 trades on a throwaway
  copy, and level 3 passes on it (section 3).

### 4.5 The real data has a strict-data gap the backtester refuses to cross
- **Symptom:** the first real level-3 run, over the full range (2025-11-03 → 2026-03-27),
  FAILED. **Both** runs stopped with the same error:
  `StrictBacktestDataError: Missing exit price(s) at 2025-12-17 14:22:44 for:
  NIFTY25D2326100PE, NIFTY25D2326100CE`.
- **Root cause:** the data, not the cloud copy. The source run stops at the same point, and the
  export-fidelity table shows the exported `delta_cache` holds every source row except the
  2,050 quarantined duplicates (0 rows only in the export). From late December the database
  has no `delta_cache` data until 2026-03-04, and no 15m data from 26 Dec to 20 Feb (Day 2
  §4.4). The backtester's strict mode refuses to price an exit there.
- **Fix:** level 3 runs on windows the backtester can complete, before and after the gap
  (D47). The full-range report is kept as evidence (`reconcile_l3_main/`).
- **Related fix in cloudsync:** when the negative test deleted the cloud's deltas, the
  backtester refused the window with `BacktestDataCoverageError` and `reconcile` crashed with
  no report. A run that refuses or crashes is now recorded as a level-3 FAIL with its error
  (D46). Driving test: `test_a_cloud_copy_missing_option_deltas_fails_and_names_the_lost_trades`.

### 4.6 Process deviation: `parity.py` was drafted before its test went red
- **What happened:** while the full-range probe was running (needed to pick a test window
  that trades), the export/backtest/diff module was written ahead of its test.
- **Mitigation:** the CLI wiring (`reconcile --levels 3`) was left out until the test had been
  run and seen failing for the right reason (no report: `--start` unknown). The negative test
  went red for a real reason (4.5) and drove D46. The trade-pairing rule (ignore `trade_id`)
  came from the probe's data, not from guesswork.

### 4.7 Smaller issues
- **Unaliased aggregates:** a compat test first compared the column label of
  `SELECT MAX(timestamp)` (`MAX(timestamp)` in SQLite, `max` in Postgres). The bot reads
  `fetchone()[0]`, so the test now compares values only for those two queries.
- **`ATTACH` needs a URI connection:** the test helper attached the working copy read-only
  with a `file:…?mode=ro` URI on a connection opened without `uri=True`. Fixed in the helper.
- **Backslashes in shell heredocs:** patch scripts passed through a heredoc lost `\\` escapes
  twice. Later edits were made with the file tools instead. No source file was affected (each
  patch asserted its target text first).
- **A blocked check:** pointing `replay` at the real database to watch it refuse was blocked
  by the agent's permission classifier, which was right to: a writer should never be aimed at
  the real database. The refusal is tested with a stand-in file instead
  (`test_commands_that_write_sqlite_refuse_the_real_database`).

## 5. Limitations and known gaps
| Limitation | Impact | Planned |
|---|---|---|
| Level 3 relies on a **shim** for a bug in the bot's backtester (D42) | Strictly, it isn't the "unchanged" backtester; the shim only supplies a log-line attribute, on both runs | Owner fixes `BacktestableBot` in the bot repo, then the shim drops out by itself (`hasattr` check) |
| Level 3 can't cover the full range: the backtester's strict mode stops at 2025-12-17 on the **source** data (4.5) | Parity shown on the windows before and after the gap, not across it | Data problem in the bot's database; report it as found |
| The quarantined `delta_cache` duplicates (2,050) aren't in the cloud copy | Export fidelity shows `delta_cache` as "not identical"; trades are still identical in both windows (section 3) | By design (spec story 12); explained in the report |
| Typed timestamps in the views: the dashboard's `exit_ts LIKE '2026-05%'` (P&L summary) has no `timestamp LIKE text` operator in Postgres | That one dashboard query would need a change to run on the cloud | Out of scope (the spec doesn't point the dashboard at Postgres); documented |
| A source `tradingsymbol` of `'N/A'` comes back as NULL from `compat.option_data/delta_cache` (contracts store NULL) | Not row-identical for such rows | 0 such rows in the real data (checked); documented |
| Unaliased aggregates (`SELECT MAX(timestamp) …`) get engine-specific column labels | None for the bot (it reads `fetchone()[0]`) | — |
| Replay: `store_market_data` never writes `vix_value`, and it recomputes SL/SH from the rows before | A replayed day differs from the original in those columns, as it would live | That's the bot's real write path; L1–L3 compare the sandbox with its own cloud |
| Replay: option, delta and SMA rows are inserted verbatim, not through bot code (D34) | Those three writers aren't exercised by the replay | Owner's decision; documented |
| Replay has no automated test (D35) | A regression would only show in a demo run | Owner's choice of seams; the refusal paths are covered by the safety test |
| `candle_indicators_computed` scans all candles (no materialization) | The drift summary takes 6.6 s on real data | Day 4 index audit / materialized view if needed |
| The level-3 work files (export, source copy: 88 MB each) go to a temp dir, or `--parity-dir` | Not kept in `artifacts/` | Re-create with the command in section 7 |

## 6. Open items carried forward
- [ ] Bot repo: commit or restore the uncommitted deleted result files on `main` (still
  present on 2026-11-07; spec prerequisite).
- [ ] **Owner (new):** fix the bot's backtester: initialise `_last_options_snapshot_timestamp`
  in `BacktestableBot.__init__` (4.4). The shim then stops applying.
- [x] Day 3: every chaos/replay run happens in a `cloudsync sandbox` (D29). Done: the replay
  ran in `replay0327`, which was dropped afterwards; the replay refuses the main pair (D49).
- [x] Day 3: chaos toggles reuse `CLOUDSYNC_FAULT` (kill mid-batch) and the bot's real
  delete-and-rebuild. Done (`kill`, `rebuild`).
- [ ] Day 4: profile the slower bulk load (Day 2 §5).
- [ ] Owner: optionally add a Claude Code permission deny rule for edits under
  `C:\Users\aryan\Desktop\AlgoTrade\db\`.
- [ ] Day 4: sync-lag view; single-daemon advisory lock.
- [ ] Day 4: roles. `bot_reader` gets `search_path = compat` and SELECT on `compat` only;
  `analyst` gets the `dq_*` views.
- [ ] Day 4: index audit on the compat views' query shapes (they filter on
  `ts AT TIME ZONE 'Asia/Kolkata'`, which a plain index on `ts` can't serve).
- [ ] Owner: register the Task Scheduler entry if wanted (`scripts\create_sync_task.bat` as
  Administrator).

## 7. How to reproduce
```bash
docker compose up -d
.venv/Scripts/python -m cloudsync migrate
.venv/Scripts/python -m cloudsync cdc-install --sqlite data/trading_bot.db
.venv/Scripts/python -m cloudsync bulk-load --sqlite data/trading_bot.db --tables market_sma_1h
.venv/Scripts/python -m cloudsync reconcile --sqlite data/trading_bot.db --levels 1,2 --out artifacts/day3/reconcile_l1_l2
.venv/Scripts/python -m cloudsync reconcile --sqlite data/trading_bot.db --levels 3 --start 2026-03-02 --end 2026-03-27 --out artifacts/day3/reconcile_l3_main_2026-03
.venv/Scripts/python -m unittest discover -s tests -t .
```
The replay, **always in a sandbox** (D29):
```bash
.venv/Scripts/python -m cloudsync sandbox create replay0327
.venv/Scripts/python -m cloudsync replay --source data/trading_bot.db --target data/sandboxes/replay0327/trading_bot.db --day 2026-03-27 --chaos revise,rebuild,kill --sync-dsn "<sandbox dsn>" --sync-every 30
.venv/Scripts/python -m cloudsync reconcile --sqlite data/sandboxes/replay0327/trading_bot.db --dsn "<sandbox dsn>" --levels 1,2,3 --start 2026-03-27 --end 2026-03-27 --out <dir>
.venv/Scripts/python -m cloudsync sandbox drop replay0327
```

## 8. Demo / presentation notes
1. **Compatibility in one query:** connect with `options='-c search_path=compat'` and run the
   bot's `SELECT * FROM market_data_1m WHERE 1=1 AND symbol = ? … ORDER BY timestamp DESC
   LIMIT 200` unchanged. Then `\d+ compat.option_data`: one view joining a header, a line and
   the contract master (3NF) back into the bot's flat row.
2. **Window functions:** `candle_indicators_computed` (named `WINDOW` frames, `count(*)` over
   the frame for pandas' `min_periods`). Then `06_indicator_drift_summary.md`: AO/Donchian
   match the bot exactly wherever both exist, and the 1h SMAs drift because the bot's stored
   series restart after gaps.
3. **The spec was wrong about the SMA table** (4.2), and the evidence for D33.
4. **Level 3:** `reconcile_l3_main_2026-03/reconciliation.md`, trade for trade. Then the
   full-range FAIL with the same error on both sides (4.5): the cloud is faithful even about
   where the original data breaks.
5. **Replay with chaos:** `replay_sandbox/02_replay_summary.json` (12 revisions, the bot's own
   1h rebuild, a killed sync with exit 75), then `replay_sandbox/reconcile/reconciliation.md`
   (L1–L3 PASS) and `04_main_pair_after_replay.txt` (main pair untouched).
6. **Honest findings about the bot:** its backtester crashes on any open position (4.4), and
   its strict mode can't cross Dec–Feb in the real data (4.5).
