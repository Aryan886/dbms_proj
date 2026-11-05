# Spec: Continuous SQLite → AWS RDS PostgreSQL sync for the AlgoTrade bot

**Labels:** `ready-for-agent`
**Course:** DBMS course project · **Owner:** 1 person + Claude Code · **Timebox:** 5 working days + 1 buffer day

## Problem Statement

My DBMS course project is "move the trading bot's locally stored SQLite data to AWS". On its own that's a file copy, and it shows almost no DBMS knowledge. The bot's database (`trading_bot.db`) also has real problems I can't currently see or prove anything about(location of the database : `C:\Users\aryan\Desktop\AlgoTrade\db`):

- The file is 2.5 GB, but about 96% of its pages are free. The real data is roughly 90 MB.
- There are no master tables and no foreign keys. Symbols, contracts and expiries are repeated as text on every row.
- The same data is stored once per timeframe (1m/5m/15m/1h), and some SMA tables are written but never read by the strategy.
- There are empty, dead and duplicated tables, and duplicate indexes on the same columns.
- `delta_cache` has 2,050 groups of duplicate rows on its natural key.
- Columns are loosely typed: timestamps are TEXT and `SL`/`SH` have no declared type.

The live data feed (Kite API) is down right now, but the bot will be used again. Whatever I build has to keep working without changes when the feed comes back. About 40 files in the bot open SQLite directly by table name, so I can't change the bot's storage without breaking it.

## Solution

The bot keeps writing to SQLite exactly as it does today. A separate local sync daemon copies every change (insert, update and delete) to a normalized PostgreSQL database on AWS RDS. Each change is applied exactly once, and the daemon recovers safely from crashes and network loss.

The cloud schema is redesigned to 3NF. Compatibility views carry the old table names and columns, so the cloud copy can stand in for the SQLite data. I can prove that with a three-level reconciliation, and the last level re-runs the unchanged NIFTY backtest on data exported from Postgres and diffs the trades.

On top of that, the project shows a set of measured DBMS concepts, all of them demoable from one script:

- Bloat and VACUUM
- WAL-mode concurrency
- An index audit with EXPLAIN ANALYZE
- Constraint enforcement with a quarantine table
- Least-privilege roles
- An audit trigger
- Point-in-time recovery
- Schema-drift handling
- Analytics views (strategy P&L, data quality, sync lag)

A replay simulator stands in for the dead Kite feed. It writes historical data through the bot's own write functions and has "chaos" toggles for revised rows, deletes and mid-batch crashes.

## User Stories

### Migration and schema
1. As the project owner, I want a working copy of `trading_bot.db` made before anything runs, so that the bot's original database is never at risk.
2. As the project owner, I want the page count, free-page count and file size recorded before and after VACUUM on the working copy, so that I can explain and prove why deletes don't shrink a SQLite file.
3. As the project owner, I want a one-time bulk load of the in-scope tables into Postgres, so that the cloud copy starts from a complete baseline before continuous sync takes over.
4. As a course evaluator, I want to see a functional-dependency analysis of the original tables, so that I can check the normalization reasoning.
5. As a course evaluator, I want before and after ER diagrams, so that I can see how the schema changed during migration.
6. As the project owner, I want an `instruments` master table (NIFTY50, INFY, INDIA VIX) referenced by foreign keys, so that symbol text is no longer repeated and orphan rows are impossible.
7. As the project owner, I want an `option_contracts` master table keyed by (instrument, expiry, strike, CE/PE) with its trading symbol, so that contract attributes are stored once and option snapshots reference a contract.
8. As the project owner, I want all 1m/5m/15m/1h candles in one `candles` table with a timeframe column, so that four identical table definitions become one.
9. As the project owner, I want timestamps stored as timezone-aware types in Asia/Kolkata, prices as fixed-precision numerics, untyped `SL`/`SH` given real types, and `option_type` restricted to CE/PE by a CHECK constraint, so that bad values can't get in and I can measure the storage and correctness gains.
10. As the project owner, I want OHLC sanity enforced by CHECK constraints (low ≤ open/close ≤ high), so that impossible candles are rejected by the database rather than by application code.
11. As the project owner, I want rows that violate a constraint to be kept in a `rejected_rows` table (source table, raw row as JSON, violated constraint, time) instead of failing the load, so that nothing is silently lost and every reject can be explained.
12. As the project owner, I want the duplicate groups in `delta_cache` resolved deterministically by keeping the highest source id and quarantining the rest, so that the cloud copy is unique and the choice is reproducible.
13. As the project owner, I want empty and dead tables (`trades`, `options_data`, `option_open_interest`, `option_open_interest_5m`) and the never-read SMA tables documented as dead schema rather than migrated, so that scope stays focused and the report explains why they were left out.

### Derived data and compatibility
14. As the trading bot (in future), I want Postgres views named and shaped exactly like `market_data_1m/5m/15m/1h`, `vix_data`, `option_data`, `delta_cache` and `signals`, so that I could read from the cloud with no query changes.
15. As a course evaluator, I want SMA, AO and Donchian computed in SQL with window functions, so that I can see derived attributes handled through views instead of stored redundantly.
16. As the project owner, I want the indicator values the bot wrote (Donchian, AO, SL/SH, observed VIX) kept as stored values that the compatibility views return, so that the strategy's inputs stay exactly the same. The strategy reads stored `donchian_mid`, and SL/SH are path-dependent.
17. As the project owner, I want a data-quality view that compares the SQL-computed indicators with the stored ones, so that drift between them is visible and explained.

### Change data capture and sync
18. As the project owner, I want SQLite switched to WAL mode on the working copy, so that the sync reader never blocks the bot's writes.
19. As a course evaluator, I want a benchmark of lock errors and write latency under concurrent writing and syncing, in rollback-journal mode vs WAL mode, so that I can see the concurrency benefit with numbers.
20. As the project owner, I want AFTER INSERT/UPDATE/DELETE triggers on every in-scope SQLite table that record (table, primary key, operation, sequence number) in a `_changelog` table, so that every change is captured. That includes the bot's `ON CONFLICT DO UPDATE` revisions and its delete-and-rebuild writes.
21. As the project owner, I want the triggers generated from each table's live column list, so that adding a table or column doesn't need hand-written trigger SQL.
22. As the project owner, I want a local sync daemon that reads changelog entries after the last applied sequence number in batches (about 1,000), so that the cloud copy keeps up continuously.
23. As the project owner, I want each batch's upserts and deletes and the move of the `sync_state` sequence number to commit in a single Postgres transaction, so that a crash at any point leaves the cloud either fully before or fully after that batch.
24. As the project owner, I want every applied change to be idempotent, so that replaying a batch after a crash produces no duplicates and no gaps.
25. As the project owner, I want the daemon to back off exponentially while Postgres is unreachable and resume where it stopped, so that network loss needs no manual action.
26. As the project owner, I want changelog entries removed from SQLite only after Postgres has acknowledged them, so that the changelog doesn't grow forever and nothing unacknowledged is lost.
27. As the project owner, I want a `sync once` mode and a `daemon` mode, so that tests and demos can run one deterministic pass, while production runs continuously.
28. As the project owner, I want the daemon to start through the same Windows mechanisms the bot already uses (batch file or Task Scheduler), so that it runs alongside the bot with no new infrastructure.

### Schema drift
29. As the project owner, I want the daemon to compare each SQLite table's column list with a stored fingerprint before syncing it, so that a future bot schema change is caught instead of corrupting the cloud copy.
30. As the project owner, I want a drifted table paused and logged while every other table keeps syncing, so that one schema change doesn't stop the whole pipeline.
31. As the project owner, I want numbered Postgres migrations tracked in a `schema_version` table, so that I can apply a migration for the drift, resume the table, and have every schema change recorded.

### Verification
32. As a course evaluator, I want a level-1 check of row counts per table, SQLite vs Postgres, so that I get a quick read on completeness.
33. As the project owner, I want a level-2 check of per-day checksums (count, sum of close, min/max timestamp) for each table, so that any mismatch can be traced to a specific day.
34. As a course evaluator, I want a level-3 parity check: export the Postgres compatibility views to a fresh SQLite file, run the unchanged NIFTY backtest against it and against the original, and diff the trade lists, so that I can see the cloud copy is a working replacement.
35. As the project owner, I want the reconciliation output saved as a readable report (pass/fail per level, per table, with the differences listed), so that it can go straight into the project report and the demo.

### Demo feed
36. As the project owner, I want a replay simulator that replays a historical trading day into the working copy at a configurable speed through the bot's own write functions, so that the triggers fire exactly as they would with a live feed.
37. As the project owner, I want a chaos toggle that revises an already-written candle, so that I can show CDC catching an update that a simple watermark would miss.
38. As the project owner, I want a chaos toggle that deletes and rebuilds rows, so that I can show deletes reaching the cloud.
39. As the project owner, I want a chaos toggle that kills the sync process mid-batch, so that I can show the exactly-once recovery live.

### Cloud: physical design, security and recovery
40. As a course evaluator, I want an index audit that removes the duplicate `idx_`/`ux_` pairs and compares B-tree and BRIN on timestamps, with EXPLAIN ANALYZE before and after for the bot's real query shapes ("latest N candles ordered by timestamp descending", "latest option snapshot"), so that index choices are backed by query plans.
41. As a course evaluator, I want dead tuples and autovacuum activity shown in Postgres after the delete-heavy chaos run, so that MVCC bloat can be compared with SQLite free pages.
42. As the project owner, I want three roles (`sync_writer` with write access to base tables only, `bot_reader` with read access to the compatibility views only, `analyst` with read access to the analytics views only), so that each consumer has least privilege.
43. As a course evaluator, I want to see a denied write attempt by `bot_reader`, so that I can see the access control actually being enforced.
44. As the project owner, I want an audit trigger on the trade-history and strategy-state tables that logs who changed what and when, with the old and new rows as JSON, so that changes to trading records can be traced.
45. As a course evaluator, I want a point-in-time recovery demo: delete a day of data on purpose, restore RDS to a moment before the delete, and show the data back, so that log-based recovery is shown on real infrastructure.
46. As the project owner, I want RDS credentials kept in a local environment file outside version control, so that secrets never appear in code or the report.

### Analytics
47. As an analyst, I want a strategy P&L view with daily P&L, cumulative P&L, win rate, max drawdown, and P&L by sub-category and exit reason, so that strategy performance can be read in SQL.
48. As the project owner, I want the trade-history table filled from backtest output, so that the P&L view has meaningful data (it holds only 8 trades today).
49. As an analyst, I want a data-quality view that lists missing 1m candles during market hours (09:15–15:30 IST), stale option snapshots, and VIX gaps, so that feed problems are found automatically.
50. As the project owner, I want a sync-lag view showing changelog backlog, last applied sequence number, apply latency per batch and rejected-row counts over time, so that I can monitor the pipeline's health.

### Demo and report
51. As the project owner, I want one demo script that runs the full story in order (VACUUM study → bulk load → replay with chaos → reconciliation → roles → analytics) and saves every measurement, so that the demo can be repeated and the report numbers are never copied by hand.
52. As a course evaluator, I want every optimisation over the original bot clearly labelled as an add-on in the demo and report, with evidence that bot behaviour didn't change, so that improvements and correctness are judged separately.

## Implementation Decisions

**Architecture**
- SQLite stays the trading bot's system of record. The only changes to the database file are additive: WAL journal mode, the changelog table and the triggers. No bot code is modified, and all development and demos run on a working copy of the database.
- The target is AWS RDS PostgreSQL. Credits are available, so the free tier isn't a constraint. Development runs against a local PostgreSQL in Docker on the same major version. Switching to RDS is a connection-string change, planned for day 4.
- The project lives in its own folder, separate from the bot repository. It reads the bot's database path and imports the bot's write functions (for the replay simulator) and its backtester (for parity) as existing interfaces.
- Language: Python, consistent with the bot.

**Modules**
1. *Prep*: makes the working copy, captures bloat statistics, runs VACUUM and records the results.
2. *Target schema*: numbered SQL migrations that create base tables, constraints, indexes, computed-indicator views, compatibility views, analytics views, roles and the audit trigger, tracked in `schema_version`.
3. *Bulk loader*: one-time load from the working copy into the base tables. It maps old rows onto the normalized shape, resolves foreign keys to the master tables, and routes constraint violations to `rejected_rows`.
4. *CDC installer*: switches the database to WAL, then generates and installs the changelog table and the per-table triggers from live column lists, and stores schema fingerprints.
5. *Sync engine*: reads changelog batches, checks fingerprints, maps changes to normalized upserts and deletes, applies each batch and the `sync_state` update in one transaction, prunes acknowledged entries, and backs off when offline. It has a `once` mode and a `daemon` mode.
6. *Reconciler*: runs levels 1, 2 and 3 and writes the report. Level 3 exports the compatibility views to a temp SQLite file and calls the existing backtester with that file as its database path.
7. *Replay simulator*: replays a chosen historical day through the bot's write functions into a working copy, with the revise, delete-and-rebuild and kill-mid-batch chaos toggles.
8. *Benchmarks*: WAL vs rollback-journal concurrency, the EXPLAIN ANALYZE index audit, and type/storage comparisons.
9. *Demo runner*: one entry point that runs the whole story and saves the artifacts.

**Schema (key shapes)**
- `instruments(id, symbol UNIQUE, kind)`: NIFTY50 index, INFY equity, INDIA VIX.
- `option_contracts(id, instrument_id → instruments, expiry_date, strike, option_type CHECK IN ('CE','PE'), tradingsymbol UNIQUE)`, unique on (instrument, expiry, strike, type).
- `candles(instrument_id → instruments, timeframe CHECK IN ('1m','5m','15m','1h'), ts, open, high, low, close, volume)`, primary key (instrument_id, timeframe, ts), with OHLC CHECK constraints.
- `candle_indicators`: one row per candle holding the values the bot wrote (AO, Donchian upper/lower/mid, SL, SH, observed VIX). **This refines the earlier "indicators only as views" decision.** The strategy reads stored `donchian_mid`, and SL/SH come from a stateful backfill that a plain window function can't express. Keeping the stored values preserves exact parity, and the computed views still show window functions and feed the drift check. The stored observed VIX is a deliberate, documented denormalization: `vix_data` is irregular point-in-time data, so the value can't be recovered reliably with a join.
- `vix_observations(ts PK, value, …)`, the option snapshot facts (from `option_data`) and the delta facts (from `delta_cache`) each reference `option_contracts`, with UNIQUE on (contract, ts).
- `signals`, `dashboard_strategy_state` and `dashboard_trade_history` are migrated with types fixed and foreign keys to `instruments`.
- Sync bookkeeping: `sync_state(source_table, last_seq, updated_at)`, `sync_batches(batch_id, seq range, row counts, started/committed time, latency)`, `rejected_rows(source_table, raw JSON, constraint, at)`, `schema_fingerprints(source_table, column list hash, status)`, `schema_version(version, applied_at)`, `audit_log(table, op, actor, at, old JSON, new JSON)`.
- Compatibility views return the exact column names and order of the original SQLite tables, including surrogate `id` columns.

**Sync semantics**
- SQLite triggers record (table, primary key, operation, monotonically increasing sequence number). The sync reads the current row at apply time, so several updates to the same row inside one batch collapse into one upsert. Deletes are applied as deletes.
- Exactly-once effect = idempotent upserts and deletes + the `sync_state` sequence number committed in the same Postgres transaction. Changelog pruning in SQLite happens only after that commit, so a crash between commit and prune is harmless: the replayed entries are idempotent.
- Duplicate resolution in `delta_cache` keeps the highest source id. The same rule applies in the bulk load and in continuous sync.
- When drift is detected, that table is paused and the others continue. Resuming requires a migration that bumps `schema_version` and refreshes the fingerprint.

**In-scope source tables:** `market_data_1m/5m/15m/1h`, `vix_data`, `option_data`, `delta_cache`, `signals`, `dashboard_strategy_state`, `dashboard_trade_history`.

**Physical design:** no partitioning (not justified at about 90 MB). The index audit decides B-tree vs BRIN on timestamps from measured plans.

**Security:** three roles granted on views and base tables as described in the user stories. Credentials live in a local environment file the owner fills in. TLS enforcement is not in scope.

## Testing Decisions

- **What makes a good test:** it checks only external behaviour, meaning what ends up in Postgres as seen through the compatibility views and the reconciliation report. It never asserts on internal mapping functions, generated SQL text or changelog layout. Tests use real SQLite files and a real, throwaway PostgreSQL. Nothing is mocked except the dead Kite API.
- **Primary seam (the only new one):** the sync CLI end to end. A test builds a temp SQLite with the bot's table-creation routine, writes data through the bot's write functions, runs CDC install and `sync once` against a throwaway Docker Postgres, and asserts on the reconciliation report and the compatibility views.
- **Existing seams reused:** the bot's write functions (they produce realistic writes, including `ON CONFLICT DO UPDATE` revisions and delete-and-rebuild), and the backtester's database-path argument (level-3 parity).
- **Cases covered through the primary seam:**
  - Insert, update and delete each propagate.
  - A revised candle is reflected in the cloud.
  - Killing the sync mid-batch and rerunning leaves no duplicates or gaps.
  - Postgres unavailable, then available: the sync catches up.
  - Duplicate `delta_cache` rows: the highest id survives and the others land in `rejected_rows`.
  - A constraint-violating candle is quarantined.
  - Adding a column to a source table pauses only that table, and applying a migration resumes it.
  - Compatibility views return identical rows to the source tables for the bot's real query shapes.
  - Levels 1–3 of the reconciliation pass on a replayed day.
  - `bot_reader` is denied writes.
- **Not covered by automated tests:** point-in-time recovery on RDS (demoed manually and recorded) and the benchmarks (measurements, not pass/fail).
- **Prior art:** the bot's existing `unittest` suite. In particular, the option snapshot pipeline test and the backtesting data-provider and runner tests build temp SQLite databases with the bot's table-creation routine and write through its write functions. The new tests use the same style and framework.

## Out of Scope

- Any change to the bot's code, its storage engine, or the SQLite tables beyond WAL mode, the changelog and the triggers.
- Pointing the live bot or the dashboard at Postgres. The compatibility views make this possible, but it isn't done here.
- Table partitioning.
- TLS enforcement and Secrets Manager.
- Option-chain analytics (PCR, max pain).
- Equity SMA tables, market SMA tables, and the empty or dead tables (documented only).
- Two-way sync and conflict resolution. Postgres is a one-way replica.
- Infrastructure-as-code. RDS is created by hand in the console.
- Repairing the Kite API feed.

## Further Notes

- **Day plan:**
  - Day 1: prep, schema, bulk load, levels 1–2.
  - Day 2: WAL, CDC, sync engine, drift handling.
  - Day 3: compatibility and indicator views, replay simulator, level-3 parity.
  - Day 4: roles, audit trigger, index audit, analytics, P&L backfill, switch to RDS.
  - Day 5: PITR first thing (the restore takes 10–20 minutes), then the report and demo rehearsal.
  - Day 6: buffer.
- **Main risk: level-3 parity.** If the backtest differs on edge cases (likely around the `delta_cache` duplicates), the fallback deliverable is a fully explained diff, not a forced match.
- **Main time risk: the PITR restore.** That's why it's scheduled first on day 5. A recorded restore is an acceptable fallback.
- **Before starting:** the bot repository has uncommitted deleted result files on `main`. The owner should commit or restore them before the bot repository is used as a dependency.
- **Optional if time allows:** an RDS read replica to show replication, since credits are available.
