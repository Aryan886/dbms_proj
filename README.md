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

## Tests

```bash
.venv/Scripts/python -m unittest discover -s tests -t .
```

The tests are end-to-end through the CLI. Each one builds a real temp SQLite with the bot's
own `create_tables` and write functions, and uses a real throwaway database on the Docker
Postgres. Only the dead Kite API is faked.
