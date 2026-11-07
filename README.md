# cloudsync — SQLite → PostgreSQL sync for the AlgoTrade bot

DBMS course project. See [SPEC.md](SPEC.md) for the full spec,
[docs/normalization.md](docs/normalization.md) for the FD analysis and ER diagrams, and the
**[project logbook](docs/logbook/README.md)** for the day-by-day record (decisions, measurements,
challenges and fixes).

## Setup (once)

```bash
py -3.14 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
copy .env.example .env      # then edit paths / DSNs if needed (.env is gitignored)
docker compose up -d        # PostgreSQL 17 on localhost:5433
```

The bot repository (`BOT_REPO` in `.env`) is used read-only, for its table-creation routine,
write functions and backtester.

## Day 1 pipeline

```bash
.venv/Scripts/python -m cloudsync prep --source "C:/Users/aryan/Desktop/AlgoTrade/db/trading_bot.db" --workdir data
.venv/Scripts/python -m cloudsync migrate
.venv/Scripts/python -m cloudsync bulk-load --sqlite data/trading_bot.db
.venv/Scripts/python -m cloudsync reconcile --sqlite data/trading_bot.db --levels 1,2 --out artifacts/day1
```

| Command | What it does | Output |
|---|---|---|
| `prep` | Copies the bot DB with SQLite's backup API (the source is opened read-only), records page/free-page/size stats, then VACUUMs the copy | `data/trading_bot.db`, `data/artifacts/prep_stats.json` |
| `migrate` | Applies pending numbered migrations from `cloudsync/migrations/`, one transaction each | `schema_version` table |
| `bulk-load` | Loads the 10 in-scope tables; rows that violate a constraint go to `rejected_rows` | per-table read/kept/rejected summary |
| `reconcile` | L1 row counts (`sqlite = postgres + rejected`) and L2 per-IST-day checksums; exits 1 on failure | `reconciliation.json` and `.md` |

## Day 2: continuous sync

Install CDC **before** the bulk load, so no write can fall between the baseline and the first
sync. Changes captured during the load are re-applied idempotently.

```bash
.venv/Scripts/python -m cloudsync migrate
.venv/Scripts/python -m cloudsync cdc-install --sqlite data/trading_bot.db
.venv/Scripts/python -m cloudsync bulk-load --sqlite data/trading_bot.db     # first time only
.venv/Scripts/python -m cloudsync sync once --sqlite data/trading_bot.db     # one deterministic pass
.venv/Scripts/python -m cloudsync sync daemon --sqlite data/trading_bot.db   # continuous
```

| Command | What it does |
|---|---|
| `cdc-install` | Switches SQLite to WAL. Creates `_changelog` and generates INSERT/UPDATE/DELETE triggers for the 10 in-scope tables from their live column lists. Stores each table's column fingerprint in Postgres (never overwritten by a re-install). |
| `sync once` | Applies every captured change in batches (`--batch-size`, default 1000). Each batch's upserts, deletes, rejects and `sync_state` move commit in one Postgres transaction; entries are pruned from SQLite only after that commit. If Postgres is unreachable it retries `--max-retries` times with exponential back-off. |
| `sync daemon` | The same, forever: sleeps `--poll` seconds when idle and backs off (0.5 s doubling, capped at 30 s) while offline. `scripts/start_sync_daemon.bat` starts it; `scripts/create_sync_task.bat` (run as Administrator) registers it in Task Scheduler at 09:10. |
| `drift-resume --table T` | Resumes a table paused by schema drift. Refused until a migration has been applied since the pause (`migrate --extra-dir DIR` adds a directory of numbered migrations). |
| `bench-wal` | Benchmarks a bot-style writer against a sync-style reader in rollback-journal and WAL mode, on copies of the database. Writes `wal_benchmark.json` and `.md`. |

Crash testing: set `CLOUDSYNC_FAULT=mid_batch:N` or `after_commit:N` and the process dies
(exit code 75) at that point of batch N.

## Day 3: compatibility views, indicators, replay, level-3 parity

```bash
.venv/Scripts/python -m cloudsync migrate          # 0006-0009: compat views, market_sma_1h, indicator + drift views
.venv/Scripts/python -m cloudsync reconcile --sqlite data/trading_bot.db --levels 1,2,3 --start 2026-01-01 --end 2026-03-27 --out artifacts/day3
.venv/Scripts/python -m cloudsync replay --source data/trading_bot.db --target <sandbox sqlite> --day 2026-03-27 --chaos revise,rebuild,kill --sync-dsn "<sandbox dsn>" --sync-every 30
```

| Object / command | What it is |
|---|---|
| schema `compat` | One view per source table, same name, columns, column order and value types as the bot's SQLite. Connect with `search_path=compat` and the bot's SQL runs unchanged. |
| `candle_indicators_computed` | SMA 5/20/50/200, SMA of highs/lows, AO and Donchian(20) computed with window functions over `candles`. |
| `dq_indicator_drift`, `dq_indicator_drift_summary` | Where the values the bot stored differ from the SQL-computed ones, per candle and per indicator. |
| `reconcile --levels 3` | Exports the compat views to a fresh SQLite, runs the bot's unchanged backtester on a copy of the source and on the export, and diffs the trades. `--parity-dir` keeps the files. |
| `replay` | Replays one day from a source into a sandbox with CDC installed, through the bot's write functions. Chaos: `revise`, `rebuild`, `kill`. Refuses the real database and the main working copy. |

## Safety: the real database is read-only

- `cloudsync` refuses (`REFUSED`, non-zero exit) any command that would write to the bot's real
  database (`SOURCE_DB`) or anywhere under `BOT_REPO` (see `cloudsync/guard.py`). Reading it
  (`prep --source`, `bulk-load`, `reconcile`) is allowed and always opens it read-only.
- Experiments never run on the main working copy. Use a throwaway pair instead:

```bash
.venv/Scripts/python -m cloudsync sandbox create exp1   # copies data/trading_bot.db + clones the PG_DSN database
.venv/Scripts/python -m cloudsync sandbox drop exp1
```

  `create` prints the sandbox's `sqlite` path and `dsn`; pass those to the bot functions and to
  `sync`/`reconcile`. Stop the sync daemon first (the Postgres clone needs no other connections).

## Tests

```bash
.venv/Scripts/python -m unittest discover -s tests -t .
```

The tests are end-to-end through the CLI. Each one builds a real temp SQLite with the bot's
own `create_tables` and write functions, and uses a real throwaway database on the Docker
Postgres. Only the dead Kite API is faked.
