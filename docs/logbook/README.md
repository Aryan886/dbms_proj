# Project logbook

This is the day-by-day record of the AlgoTrade SQLite → PostgreSQL project. Each day has its
own file covering what was built, the decisions taken (and who took them), the measurements,
the problems met and how they were solved, and what is still open.

It's written for three readers:
- **Teammates**, catching up on what changed and why.
- **The examiner**, as evidence of the process: decisions, trade-offs and real numbers.
- **The next agent session**, to pick up where the last one stopped.

## Index

| Day | Date | Theme (from the spec's day plan) | Status | Log |
|---|---|---|---|---|
| 1 | 2026-11-05 | Prep, schema, bulk load, reconciliation levels 1–2 | ✅ Done | [day-01.md](day-01.md) |
| 2 | 2026-11-06 | WAL, CDC triggers, sync engine, drift handling | ✅ Done | [day-02.md](day-02.md) |
| 3 | 2026-11-07 | Compatibility & indicator views, replay simulator, level-3 parity | ✅ Done | [day-03.md](day-03.md) |
| 4 | — | Roles, audit trigger, index audit, analytics, P&L backfill, switch to RDS | ⏳ Not started | — |
| 5 | — | PITR demo, report, demo rehearsal | ⏳ Not started | — |
| 6 | — | Buffer | ⏳ Not started | — |

## Decision register

Every design decision lives here so it can be traced back to a day and an owner. "Owner" is
who decided: **Team** means the project owner chose it when asked; **Agent** means the agent
chose it as a sensible default and recorded it.

| # | Day | Decision | Owner | Why |
|---|---|---|---|---|
| D1 | 1 | PostgreSQL **17** locally (Docker) and later on RDS | Team | Mature on RDS; same major version in dev and cloud |
| D2 | 1 | **Split typing**: NUMERIC(12,2) for exchange prices, double precision for computed values | Team | OHLC/spot/trade prices round-trip exactly at 2 dp; option ltp/iv/delta don't, and parity needs the exact floats |
| D3 | 1 | Trade `symbol` parsed into `option_contracts` | Team | Removes a transitive dependency; trades reference a real contract |
| D4 | 1 | Monthly trade symbols: expiry **derived** (last Tue, last Thu before Sep-2025) and flagged `expiry_source='derived'` | Team | The expiry day isn't in monthly symbols; the flag keeps it explainable |
| D5 | 1 | Option snapshots split into a **header** (`option_chain_snapshots`, holds spot) and **lines** | Team | Measured FD (instrument, ts) → spot, so strict 3NF |
| D6 | 1 | All seams in [SPEC.md](../../SPEC.md) approved; tests read base tables until the Day-3 compatibility views exist | Team | "Everything required for a smooth presentation" |
| D7 | 1 | Own venv on Python 3.14; pandas/numpy/scipy pinned to the bot's versions | Agent | Bot write functions and the backtester behave identically in tests |
| D8 | 1 | Working copy VACUUMed in place, after measuring | Agent | Every later step runs on the compact 88 MB file |
| D9 | 1 | INFY seeded in `instruments`, `equity_*` tables not migrated | Agent | The spec lists INFY as an instrument but `equity_*` isn't in scope |
| D10 | 1 | `delta_cache` duplicates: highest source id wins, others quarantined, in **either arrival order** | Spec + Agent | The spec fixes the rule; arrival-order independence is needed for CDC replays |
| D11 | 1 | Postgres (CHECK/FK/NOT NULL) decides what's invalid; Python only routes failures | Agent | "Rejected by the database rather than by application code" |
| D12 | 1 | L1 passes when `sqlite = postgres + rejected` | Agent | Nothing silently lost; every reject explained |
| D13 | 2 | Triggers record only (table, pk, op, seq); rows read at apply time | Spec | Updates collapse; replays idempotent |
| D14 | 2 | `_changelog.seq` is AUTOINCREMENT | Agent | A pruned-empty rowid table restarts at 1, so changes would be skipped silently |
| D15 | 2 | One cursor per table in `sync_state`; paused tables skipped | Spec + Agent | A global cursor can't pass a paused table without losing entries |
| D16 | 2 | Natural-key tables: delete the cloud image before re-applying; source-pk tables: upsert | Agent | No stale/clashing rows after id moves or rebuilds; FK-safe |
| D17 | 2 | Rejects of touched rows re-decided every batch | Agent | A corrected row leaves quarantine (Day-1 gap) |
| D18 | 2 | Deleting a `delta_cache` survivor promotes the highest quarantined sibling | Agent | "Highest remaining id wins" survives deletes |
| D19 | 2 | Observed contract beats derived (key corrected or merged, observed tradingsymbol kept) | Agent | Holiday-shifted monthly expiries (Day-1 gap) |
| D20 | 2 | Fingerprints in Postgres, never overwritten by re-install; resume needs a newer `schema_version` | Agent (implements Spec) | Drift can't be silently accepted |
| D21 | 2 | Fault injection via `CLOUDSYNC_FAULT=mid_batch:N` / `after_commit:N` | Agent | Deterministic crash tests; reused by the Day-3 chaos toggle |
| D22 | 2 | `once` retries with back-off then fails; `daemon` retries forever (0.5 s doubling, cap 30 s) | Agent | Back-off demoable without a daemon |
| D23 | 2 | WAL benchmark: two processes, bot's 5 s busy timeout plus a 0.5 s run | Agent | Measures SQLite locking, not the GIL |
| D24 | 2 | Real-data delete test uses the bot's own `backfill_market_data_1h` on the working copy | Agent | Real code path; changed the working copy's 1h data (day-02 §4.4) |
| D25 | 2 | Deletes pipelined (`executemany`), per-row fallback only on failure | Agent | Measured 3.0 s → 0.16 s per 1,000-change batch |
| D26 | 2 | Daemon via `.bat` + Task Scheduler at 09:10 | Agent (implements Spec) | Same mechanism as the bot |
| D27 | 2 | `migrate --extra-dir` for drift migrations | Agent | Ship a drift fix without editing the package |
| D28 | 2 | **The bot's real database is read-only: only read actions on it** | Team | Owner's rule after the 1h incident (day-02 §4.4); enforced by `cloudsync/guard.py` |
| D29 | 2 | **Every experiment runs in a throwaway sandbox**, never on the main working copy or cloud database | Team | Owner's rule after the same incident |
| D30 | 2 | Guard protects `SOURCE_DB` and all of `BOT_REPO`, checked inside each writing function | Agent | No path into the bot repo can be written |
| D31 | 2 | Sandbox = backup-API SQLite copy + `CREATE DATABASE … TEMPLATE` cloud clone | Agent | Sandbox syncs never touch the main cloud database |
| D32 | 2 | Main pair rebuilt from the real database and proven identical row for row | Team + Agent | Undo the 1h divergence with proof for every table |
| D33 | 3 | **`market_sma_1h` migrated as stored data** (11th in-scope table), changing spec story 13 | Team | The backtester reads it and the strategy uses 1h sma_20/50/200; the stored values can't be recomputed |
| D34 | 3 | Replay: candles/VIX/signals through bot writers; option, delta and SMA rows inserted verbatim | Team | The bot's option/delta/SMA writers stamp now(), call Kite or recompute |
| D35 | 3 | Day-3 seams: compat views, indicator + drift views, level 3. Replay checked by a recorded sandbox run | Team | Owner's choice |
| D36 | 3 | Level-3 test data: a slice of the working copy that is known to trade | Team | Two empty trade lists prove nothing |
| D37 | 3 | Compat views in their own schema `compat` (`search_path = compat`) | Agent | Base tables already use some source names |
| D38 | 3 | Compat view types: IST `timestamp` and `float8` | Agent | Real comparison semantics; the typing gain stays visible |
| D39 | 3 | Compat column order follows production, not `create_tables()` | Agent (implements Spec) | They differ for 1m/5m/15m |
| D40 | 3 | Composite source keys recorded as `col1\|col2` text in `_changelog` | Agent | `rowid` can change on VACUUM |
| D41 | 3 | No FK from `candle_sma` to `candles` | Agent | The bot writes/deletes them independently; drift view reports orphans |
| D42 | 3 | **Backtester shim**: class-level default for the attribute the bot's backtester lacks, on both runs | Team | The committed backtester crashes on any open position; no bot file changes |
| D43 | 3 | Each backtest in its own process on a copy (backup of the source, and the export) | Agent | The backtester opens its DB read-write; no shared module state |
| D44 | 3 | Export tables created from the source's own DDL, filled in source-key order | Agent | Same columns, affinities, indexes and ids as the compared database |
| D45 | 3 | Level 3 also reports per-table export fidelity (informational) | Agent | Shows which table caused a trade difference |
| D46 | 3 | A backtest that refuses or crashes is a level-3 result (FAIL with its error), not a crash of `reconcile` | Agent | The real data has a strict-data gap (day-03 §4.5) |
| D47 | 3 | Real level-3 runs use windows the backtester can complete (before and after the Dec–Feb gap) | Agent | The full range stops on 2025-12-17 on the source itself |
| D48 | 3 | `bulk-load --tables` loads a subset (a table added by a later migration) | Agent | Load 1,235 SMA rows without re-loading 730k rows |
| D49 | 3 | Replay refuses the real database and the main working copy, and needs CDC on its target | Agent (implements D29) | The replay rewinds a day with DELETEs |

## How to add a day

1. Copy [_template.md](_template.md) to `day-NN.md`.
2. Fill every section. Write "none" rather than deleting a section, so the examiner can see it
   was considered.
3. Put numbers in the log only if they came from a real run, and say where the artifact is.
4. Add the day to the index, and any new decisions to the decision register.
5. Carry the previous day's open items forward: close them, or keep them listed.
