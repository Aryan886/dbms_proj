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
| 2 | — | WAL, CDC triggers, sync engine, drift handling | ⏳ Not started | — |
| 3 | — | Compatibility & indicator views, replay simulator, level-3 parity | ⏳ Not started | — |
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

## How to add a day

1. Copy [_template.md](_template.md) to `day-NN.md`.
2. Fill every section. Write "none" rather than deleting a section, so the examiner can see it
   was considered.
3. Put numbers in the log only if they came from a real run, and say where the artifact is.
4. Add the day to the index, and any new decisions to the decision register.
5. Carry the previous day's open items forward: close them, or keep them listed.
