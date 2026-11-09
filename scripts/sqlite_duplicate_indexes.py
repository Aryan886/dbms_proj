"""Measure the bot's duplicate idx_/ux_ index pairs on a THROWAWAY SQLite copy (spec story 40).

market_data_1m/5m/15m each carry idx_<t>_symbol_timestamp AND ux_<t>_symbol_timestamp on the
same columns (symbol, timestamp). The unique one is needed (the bot's ON CONFLICT relies on it);
the plain one is pure duplication. This drops the plain ones in the copy and records the file
size, page counts and query plans before and after. The Postgres schema never had them.

usage: python scripts/sqlite_duplicate_indexes.py SANDBOX_SQLITE OUT_JSON
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cloudsync.guard import assert_writable  # noqa: E402

TIMEFRAMES = ("1m", "5m", "15m")
QUERY = ("SELECT * FROM market_data_1m WHERE 1=1 AND symbol = ? AND timestamp >= ? AND timestamp <= ? "
         "ORDER BY timestamp DESC LIMIT 200")


def snapshot(conn, path):
    page = conn.execute("PRAGMA page_size").fetchone()[0]
    plan = [r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + QUERY,
                                       ("NIFTY50", "2026-03-27 09:15:00", "2026-03-27 15:30:00"))]
    t0 = time.perf_counter()
    for _ in range(200):
        conn.execute(QUERY, ("NIFTY50", "2026-03-27 09:15:00", "2026-03-27 15:30:00")).fetchall()
    return {"file_bytes": Path(path).stat().st_size, "page_size": page,
            "page_count": conn.execute("PRAGMA page_count").fetchone()[0],
            "indexes": [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND "
                                                    "tbl_name LIKE 'market_data_%' AND sql IS NOT NULL ORDER BY 1")],
            "plan": plan, "query_ms_avg_of_200": round((time.perf_counter() - t0) * 1000 / 200, 3)}


def main(path, out):
    assert_writable(Path(path), "duplicate-index study (drops indexes)")
    conn = sqlite3.connect(path)
    conn.execute("VACUUM")
    before = snapshot(conn, path)
    for tf in TIMEFRAMES:
        conn.execute(f"DROP INDEX IF EXISTS idx_market_data_{tf}_symbol_timestamp")
    conn.commit()
    conn.execute("VACUUM")
    after = snapshot(conn, path)
    conn.close()
    result = {"before": before, "after": after,
              "saved_bytes": before["file_bytes"] - after["file_bytes"],
              "saved_pages": before["page_count"] - after["page_count"]}
    Path(out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:3])
