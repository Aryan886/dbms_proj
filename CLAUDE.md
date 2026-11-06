# Project instructions for agents

Spec: [SPEC.md](SPEC.md). Work test-first in vertical slices (one failing test, then minimal code).
Tests run end-to-end through the `cloudsync` CLI against real SQLite and the Docker Postgres
(`docker compose up -d`, port 5433). Run them with `.venv/Scripts/python -m unittest discover -s tests -t .`

## Data safety (required)

- **The bot's real database (`SOURCE_DB`, `C:\Users\aryan\Desktop\AlgoTrade\db\trading_bot.db`)
  and everything under `BOT_REPO` are read-only.** Open SQLite there only with `?mode=ro`. Never
  pass them to a command or bot function that writes. `cloudsync` enforces this in
  `cloudsync/guard.py` (commands exit with `REFUSED`); bot functions you call directly are not
  guarded, so always pass them an explicit `db_path` that is not the real database.
- **The main working copy (`data/trading_bot.db`) and the main cloud database (`PG_DSN`) are for the
  pipeline only** (`prep`, `cdc-install`, `bulk-load`, `sync`, `reconcile`). Any experiment, manual
  test, benchmark or bot write path runs on a throwaway pair:
  `cloudsync sandbox create NAME`, then use the `sqlite` path and `dsn` it prints, then
  `cloudsync sandbox drop NAME`. Automated tests already use their own temp SQLite and Postgres.
- After a session that touched data, check that the real database's SHA-256 still matches
  `artifacts/day2/rebuild/real_db_sha256.txt`.

## Logbook (required)

The team presents `docs/logbook/` to the examiner, so keep it current as part of the work,
not as an afterthought:

- Each working day has its own file, `docs/logbook/day-NN.md`, created from
  `docs/logbook/_template.md`. Fill every section; write "none" rather than deleting one.
- While working, record each slice, decision, challenge (symptom → root cause → fix → how it
  was verified) and limitation in that day's file.
- Before ending a session, update the index and the decision register in
  `docs/logbook/README.md`, and carry open items forward.
- Only put numbers in the log that came from a real run, and name the artifact they came from.
- Mark each decision's owner: **Team** (the project owner chose), **Agent** (a default the
  agent picked) or **Spec**.
