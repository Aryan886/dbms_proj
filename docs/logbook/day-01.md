# Day 1 — Prep, schema, bulk load, reconciliation L1–L2 (2026-11-05)

**Goal (from the spec's day plan):** make a safe working copy and study bloat; design and
migrate the normalized schema; bulk-load the in-scope tables; prove completeness with
reconciliation levels 1 and 2.

**Outcome:** ✅ Done. The real 2.5 GB database was reduced to 88 MB, loaded into PostgreSQL 17,
and **passes level 1 and level 2 reconciliation for all 10 tables**. 15 end-to-end tests pass.

---

## 1. What was built

The work was test-first in **vertical slices**: one failing test, the minimum code to pass it,
then the next slice. Every test runs the real `cloudsync` CLI. It uses a real temp SQLite built
by the bot's own `create_tables` and write functions, and a real throwaway Postgres database.
Only the dead Kite API is faked.

| # | Slice | Driving test | Main files |
|---|---|---|---|
| 1 | Working copy + VACUUM study | `test_prep_makes_vacuumed_working_copy_and_leaves_source_untouched` | `cloudsync/prep.py` |
| 2 | Numbered migrations, `schema_version` | `test_migrate_records_versions_and_is_idempotent`, `test_master_instruments_are_seeded` | `cloudsync/migrate.py`, `migrations/0001_base_schema.sql` |
| 3 | Tracer bullet: one candle table → Postgres → L1 report | `test_bot_candles_load_and_level1_counts_match` | `cloudsync/tables.py`, `bulk_load.py`, `reconcile.py` |
| 4 | L2 per-day checksums that pinpoint a corrupted day | `test_level2_daily_checksums_pass_then_pinpoint_a_corrupted_day` | `cloudsync/reconcile.py` |
| 5 | `vix_data` → `vix_observations` | `test_vix_observations_load_and_reconcile` | `cloudsync/tables.py` |
| 6 | `signals` | `test_signals_load_and_reconcile` | `cloudsync/tables.py` |
| 7 | `option_data` → `option_contracts` master + snapshots | `test_option_snapshots_load_with_contract_master_and_reconcile` | `cloudsync/tables.py` |
| 8 | `delta_cache` → `delta_snapshots` (bot's delta builder, fake Kite) | `test_delta_snapshots_load_and_reconcile` | `cloudsync/tables.py` |
| 9 | Dashboard tables + tradingsymbol → contract resolution | `test_dashboard_tables_load_with_derived_contracts_and_reconcile`, `test_weekly_trade_symbol_reuses_the_observed_contract` | `migrations/0002_trade_contract_resolver.sql` |
| 10 | Quarantine of constraint-violating rows | `test_constraint_violating_candle_is_quarantined_not_lost` | `cloudsync/apply.py` |
| 11 | `delta_cache` duplicates: highest id wins, rest quarantined | `test_delta_cache_duplicates_keep_highest_id_and_quarantine_the_rest` | `migrations/0003_delta_dedup_and_idempotent_rejects.sql` |
| 12 | Option-chain header/line split (strict 3NF) + spot FD enforced | `test_option_chain_spot_is_stored_once_per_snapshot`, `test_option_row_contradicting_its_snapshot_spot_is_quarantined` | `migrations/0004_option_chain_header_line.sql` |
| — | Real run on the full database | (manual run; artifacts below) | `artifacts/day1/` |
| — | FD analysis, before/after ER diagrams, dead-schema list | — | [docs/normalization.md](../normalization.md) |

**CLI after Day 1:** `prep`, `migrate`, `bulk-load`, `reconcile` (see the [project README](../../README.md)).

## 2. Decisions taken

| # | Decision | Owner | Alternatives considered | Why |
|---|---|---|---|---|
| D1 | PostgreSQL 17 | Team | 16, 18 | Mature on RDS; the same version locally and in the cloud |
| D2 | Split typing (NUMERIC(12,2) for prices, float8 for computed values) | Team | NUMERIC everywhere; unconstrained NUMERIC | Measured: OHLC/spot/trade prices are exact at 2 dp; 126k option_data and 181k delta_cache `ltp` values are not |
| D3 | Parse trade symbols into `option_contracts` | Team | FK to instrument only, keep text | A trade should reference its contract |
| D4 | Derive monthly expiry, flag it `derived` | Team | Quarantine the trade; contract_id NULL | Keeps every trade, and the guess is visible and explainable |
| D5 | Header/line split for option snapshots | Team | Keep spot per row and document it | Measured FD (instrument, ts) → spot in 160/160 snapshots, so strict 3NF |
| D6 | Approve all seams; base tables as the interim assertion target | Team | Fewer seams | Smooth, complete presentation |
| D7 | Venv on Python 3.14; pin pandas 3.0.1, numpy 2.4.2, scipy 1.17.1 | Agent | System Python 3.12 | Match the bot's venv so its write functions behave the same |
| D8 | VACUUM the working copy in place, after measuring | Agent | Separate copy for the study | All later work uses the compact file |
| D9 | Seed INFY, don't migrate `equity_*` | Agent | Migrate equity tables | Not in the spec's in-scope list |
| D10 | Duplicate rule independent of arrival order | Agent (extends Spec) | Rule that only works in id order | Day-2 CDC replays can arrive out of order |
| D11 | Postgres, not Python, decides what's invalid (CHECK/FK/NOT NULL); Python only routes failures | Agent | Re-implement the checks in Python | The spec asks for rejects "by the database rather than by application code" |
| D12 | L1 passes when `sqlite = postgres + rejected` | Agent | Strict equality | "Nothing silently lost; every reject explained" |

## 3. Measurements (real runs only)

| Metric | Value | Artifact |
|---|---|---|
| Source file size | 2,569,867,264 bytes (2.39 GiB) | `data/artifacts/prep_stats.json` |
| Pages / free pages before VACUUM | 627,409 / 605,183 (**96.46 % free**) | same |
| File size after VACUUM | 88,547,328 bytes (84 MiB), 21,618 pages, 0 free | same |
| VACUUM time | 5.9 s (whole prep incl. 2.5 GB backup copy: 54 s) | same, `artifacts/day1/01_prep.log` |
| Source journal mode | `delete` (rollback journal); WAL comes on Day 2 | — |
| Bulk load | 731,141 rows in 2 min 8 s | `artifacts/day1/03_bulk_load.log` |
| `delta_cache` | 348,109 read → 346,059 kept, **2,050 quarantined** (= the spec's 2,050 duplicate groups) | `artifacts/day1/reconciliation.md` |
| Option-chain headers after 0004 | 160 (= the 160 real chain fetches) | `artifacts/day1/05_migrate_0004.log` |
| Migration 0004 on live data | 8.6 s (336,480 rows backfilled) | same |
| Postgres database size | 151 MB before 0004 | — |
| Reconciliation | **L1 PASS 10/10, L2 PASS 10/10** (0 mismatched days) | `artifacts/day1/reconciliation.md` |
| Test suite | 15 tests, ~42 s, all pass | `python -m unittest discover -s tests -t .` |

**Data-profiling facts measured on the source** (used in the FD analysis):
- 0 OHLC rows violate low ≤ open/close ≤ high, so the CHECKs cost nothing on real data.
- `SL`/`SH` in 1m: 32,534 REAL, 9 NULL; no declared type.
- `option_data`: 2,103 tradingsymbols ↔ 2,103 contract tuples (1:1); 0 duplicates on (ts, tradingsymbol).
- `(symbol, ts) → spot_price`: holds in option_data (160/160); **fails** in delta_cache (65 of 13,676 timestamps).

## 4. Challenges and how they were fixed

### 4.1 Docker Desktop crashed on start
- **Symptom:** "An unexpected error occurred … remove …\Docker\run\sailor-ingest.sock: The file
  cannot be accessed by the system."
- **Root cause:** a Unix-socket file left over from 29 Aug had become a broken NTFS reparse
  point (`fsutil` → Error 1920). Docker deletes it on startup and crashed when it couldn't.
  `Remove-Item` and `del` failed on it too.
- **Fix:** renamed the parent folder (`Docker\run` → `run.stale-20261105`) so Docker
  recreates a clean one. The owner then fully quit and restarted Docker Desktop (the agent
  wasn't permitted to kill processes).
- **Verified:** `docker info` reports server 29.9.2; Postgres 17.11 came up on port 5433.
- **Note for teammates:** if this recurs, rename that folder again or reboot. The stale folder
  can be deleted after a reboot.

### 4.2 Bot module imports needed packages the bot venv doesn't list
- **Symptom:** `ModuleNotFoundError: pydantic` while building the test database.
- **Root cause:** `server/dashboard_store.py` (which creates the dashboard tables) imports
  pydantic models.
- **Fix:** added `pydantic` to `requirements.txt` and pinned the other bot dependencies to the
  bot venv's exact versions.

### 4.3 `DashboardStore()` didn't create the dashboard tables
- **Root cause:** the constructor only stores the path; `initialize()` creates the tables
  **and seeds 3 strategies plus 8 demo trades**.
- **Fix:** the test fixture calls `initialize()` with a fixed reference time.
- **Consequence worth reporting:** the 8 rows in production `dashboard_trade_history` are this
  seeded demo data, so the Day-4 P&L backfill from backtest output matters.

### 4.4 The bot's `create_tables` doesn't produce the production schema
- **Symptom:** the bot's delta builder failed with "table delta_cache has no column named ltp".
- **Root cause:** production gained `delta_cache.ltp` and `tradingsymbol` later through
  `ALTER TABLE`; `create_tables` never got them. The bot's own tests hand-create `delta_cache`.
- **Fix:** the fixture applies the same additive ALTERs. A one-off comparison then confirmed
  the fixture's column **sets** match production for all 10 in-scope tables.
- **Remaining difference:** column **order** in `market_data_1m/5m/15m` (production has
  `…, SL, SH, vix_value`; the fixture has `…, vix_value, SL, SH`). The loader selects columns
  by name, so it's harmless today. It matters for Day-2 fingerprints and Day-3 compatibility
  views, which must use production's order.

### 4.5 A function's insert was invisible to its caller's statement
- **Symptom:** `NOT NULL violation on dashboard_trade_history.instrument_id`, even though the
  contract was resolved.
- **Root cause:** `resolve_trade_contract()` inserted a new contract, but a sibling subquery
  in the same INSERT … SELECT runs on the **statement's snapshot** taken before the call, so
  it couldn't see the new row (MVCC visibility).
- **Fix:** the function returns both `contract_id` and `instrument_id` (OUT parameters).
- **Worth presenting:** a concrete MVCC snapshot-visibility example.

### 4.6 PL/pgSQL name clash
- **Symptom:** "column reference instrument_id is ambiguous … could refer to either a PL/pgSQL
  variable or a table column".
- **Fix:** `#variable_conflict use_column` in the function.

### 4.7 Function overload resolution
- **Symptom:** `function apply_delta_cache(smallint, unknown, …, double precision) does not exist`.
- **Root cause:** the driver sends `spot_price` as float8, and Postgres has no *implicit* cast
  from float8 to numeric when it picks a function.
- **Fix:** explicit casts in the call.

### 4.8 Duplicates were being silently overwritten, and reconciliation caught it
- **Symptom:** before the dedup slice, the duplicate test failed at **L1** (sqlite 2n,
  postgres n, rejected 0).
- **Root cause:** the plain upsert on (contract, ts) overwrote the earlier row without a trace.
- **Fix:** `apply_delta_cache()` keeps the highest source id and writes the loser to
  `rejected_rows`, whichever row arrives first. A unique key on
  `rejected_rows(source_table, source_pk)` makes replays idempotent.
- **Worth presenting:** this shows the reconciler working as a safety net, not just a report.

### 4.9 Third normal form violation found by measuring, not assuming
- **Finding:** `(instrument, ts) → spot_price` holds for every option-chain fetch, so storing
  spot per option line was a transitive dependency.
- **Fix:** migration 0004 adds the header table, **backfills from data already loaded**,
  rewires the lines, drops the redundant columns, and enforces the FD in `apply_option_data()`
  (a contradicting row is rejected as `option_chain_snapshots_spot_fd`).
  It ran on the live database in 8.6 s and reconciliation still passed.

### 4.10 Smaller issues
- **Possibly flaky test:** two option-chain writes in the same second would collide on
  (contract, ts). Fixed by using one snapshot per test; duplicates are covered by the
  quarantine tests instead.
- **Misleading summary:** bulk-load reported `rejected: 0` for `delta_cache` because those
  rejections happen inside a SQL function. It now counts from `rejected_rows`.
- **Process deviation:** the migrate code was written before its test had been seen failing,
  because Docker was down. Fixed after the fact by removing the migration file, confirming
  both tests fail (red), then restoring it (green).

## 5. Limitations and known gaps

| Limitation | Impact | Planned |
|---|---|---|
| Derived monthly expiry ignores exchange holidays | A derived expiry can be off by a day; it's flagged `derived` | Document; replace with observed data if seen |
| If a trade creates a derived contract **before** the matching option data arrives (possible in CDC), the observed row's tradingsymbol would clash | That option row would be quarantined | Day 2: reconcile derived → observed in `upsert_observed_contract` |
| A row quarantined and later corrected in SQLite stays in `rejected_rows` | L1 would over-count rejects | Day 2: clear the reject when the source pk applies successfully |
| `option_data` duplicates on (snapshot, contract) are overwritten, not quarantined | Would show as an L1 mismatch (detected, not lost); 0 such rows in real data | Revisit if CDC produces any |
| Tests assert on base tables | Interim; the spec wants compatibility views | Day 3 |
| No CDC yet: the load is one-time, so later bot writes aren't synced | — | Day 2 |
| Running on local Docker, not RDS | Connection-string change only | Day 4 |
| L2 float sums compared with 1e-9 relative tolerance | Needed because summation order differs; real differences are far larger | Keep; documented in `reconcile.py` |

## 6. Open items carried forward
- [x] `git init` the project folder and make the first commit: done, `d866018` on `main`. The
  88 MB working database (`data/*`) and `.env` are ignored. The small measurement files in
  `artifacts/` and `data/artifacts/` are tracked as evidence.
- [ ] Bot repo: commit or restore the uncommitted deleted result files on `main` (spec prerequisite).
- [ ] Day 2: fingerprints must use production's column order (see 4.4).
- [ ] Day 2: the three limitations marked "Day 2" above.

## 7. How to reproduce
```bash
docker compose up -d
.venv/Scripts/python -m cloudsync prep --source "C:/Users/aryan/Desktop/AlgoTrade/db/trading_bot.db" --workdir data
.venv/Scripts/python -m cloudsync migrate
.venv/Scripts/python -m cloudsync bulk-load --sqlite data/trading_bot.db
.venv/Scripts/python -m cloudsync reconcile --sqlite data/trading_bot.db --levels 1,2 --out artifacts/day1
.venv/Scripts/python -m unittest discover -s tests -t .
```

## 8. Demo / presentation notes
1. **Bloat story:** open `data/artifacts/prep_stats.json` and show 96.46 % free pages and
   2.4 GiB → 84 MiB. The point to make: SQLite `DELETE` marks pages free but doesn't shrink
   the file; only VACUUM rebuilds it.
2. **Normalization:** [docs/normalization.md](../normalization.md). Walk through the FDs, then
   compare the before/after ER diagrams. Highlight the spot-price FD, which was *measured*,
   and why delta_cache is different (65 counterexamples).
3. **Constraints that do real work:** run the quarantine tests, or show `rejected_rows` with
   2,050 `delta_snapshots_pkey` entries, each with its JSON row and the reason.
4. **Reconciliation:** show `artifacts/day1/reconciliation.md`. Then, live, corrupt one candle
   (`UPDATE candles SET close = close + 0.05 WHERE …`), re-run `reconcile`, and show that L2
   names the exact day.
5. **MVCC talking point:** challenge 4.5 (snapshot visibility inside one statement).
