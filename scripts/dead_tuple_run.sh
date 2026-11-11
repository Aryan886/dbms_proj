#!/usr/bin/env bash
# Story 41 run: delete-heavy chaos replay on a sandbox pair, with dead-tuple samples
# before, right after, and every 60 s for 15 min while autovacuum catches up.
# Usage: bash scripts/dead_tuple_run.sh SANDBOX_NAME OUT_DIR   (sandbox must exist, CDC on)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python.exe; [ -x "$PY" ] || PY=.venv/Scripts/python
NAME=$1; OUT=$2; mkdir -p "$OUT"
SQLITE=data/sandboxes/$NAME/trading_bot.db
DSN=$("$PY" -c "
from dotenv import dotenv_values; import psycopg
main = dotenv_values('.env')['PG_DSN']
db = psycopg.conninfo.conninfo_to_dict(main)['dbname'] + '_sbx_$NAME'
print(psycopg.conninfo.make_conninfo(main, dbname=db))")
WRITER=$("$PY" -c "import psycopg,sys; print(psycopg.conninfo.make_conninfo(sys.argv[1], options='-c role=sync_writer'))" "$DSN")
S="$OUT/samples.jsonl"; : > "$S"
"$PY" scripts/dead_tuple_study.py "$SQLITE" "$DSN" "$S" before
start=$(date +%s)
"$PY" -m cloudsync replay --source data/trading_bot.db --target "$SQLITE" --day 2026-03-27 \
    --chaos revise,rebuild,kill --sync-dsn "$WRITER" --sync-every 30 > "$OUT/replay.log" 2>&1 || echo "replay exit $?" >> "$OUT/replay.log"
echo "replay+sync seconds: $(( $(date +%s) - start ))" | tee "$OUT/timing.txt"
"$PY" -m cloudsync sync once --sqlite "$SQLITE" --dsn "$WRITER" > "$OUT/final_sync.log" 2>&1
"$PY" scripts/dead_tuple_study.py "$SQLITE" "$DSN" "$S" after_replay
for i in $(seq 1 15); do sleep 60; "$PY" scripts/dead_tuple_study.py "$SQLITE" "$DSN" "$S" "t+${i}m"; done
"$PY" scripts/dead_tuple_study.py --report "$S" "$OUT/dead_tuples.md"
echo done
