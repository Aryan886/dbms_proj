"""Story 41: MVCC dead tuples and autovacuum in Postgres vs free pages in SQLite.

Run it on a sandbox pair only (D29). One call takes one sample and appends it to
a JSON-lines file:

    python scripts/dead_tuple_study.py SQLITE DSN OUT.jsonl LABEL

Each sample holds, per Postgres base table: live/dead tuples, cumulative
inserts/updates/deletes, (auto)vacuum counts and times, and total size; plus the
autovacuum settings and, for SQLite, page_count / freelist_count / file size
(SQLite reuses free pages but never returns them to the OS without VACUUM).
`--report OUT.jsonl OUT.md` turns the samples into a Markdown table.
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import psycopg

TABLES = ("candles", "candle_indicators", "candle_sma", "option_snapshots", "option_chain_snapshots",
          "delta_snapshots", "vix_observations", "signals")
SETTINGS = ("autovacuum", "autovacuum_naptime", "autovacuum_vacuum_threshold",
            "autovacuum_vacuum_scale_factor", "autovacuum_vacuum_insert_threshold",
            "autovacuum_vacuum_insert_scale_factor")


def sample(sqlite_path: str, dsn: str, label: str) -> dict:
    out = {"label": label, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT pg_stat_clear_snapshot()")
        rows = conn.execute("""
            SELECT relname, n_live_tup, n_dead_tup, n_tup_ins, n_tup_upd, n_tup_del, n_tup_hot_upd,
                   vacuum_count, autovacuum_count, analyze_count, autoanalyze_count,
                   to_char(last_autovacuum, 'YYYY-MM-DD HH24:MI:SS TZ'),
                   pg_total_relation_size(relid), n_mod_since_analyze
            FROM pg_stat_user_tables WHERE schemaname = 'public' AND relname = ANY(%s) ORDER BY relname""",
                            (list(TABLES),)).fetchall()
        keys = ("live", "dead", "ins", "upd", "del", "hot_upd", "vacuum_count", "autovacuum_count",
                "analyze_count", "autoanalyze_count", "last_autovacuum", "total_bytes", "mod_since_analyze")
        out["pg"] = {r[0]: dict(zip(keys, r[1:])) for r in rows}
        out["pg_settings"] = {s: conn.execute("SELECT current_setting(%s)", (s,)).fetchone()[0] for s in SETTINGS}
        out["pg_database_bytes"] = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
    uri = f"file:{Path(sqlite_path).resolve().as_posix()}?mode=ro"
    sq = sqlite3.connect(uri, uri=True)
    try:
        page_size = sq.execute("PRAGMA page_size").fetchone()[0]
        page_count = sq.execute("PRAGMA page_count").fetchone()[0]
        freelist = sq.execute("PRAGMA freelist_count").fetchone()[0]
    finally:
        sq.close()
    out["sqlite"] = {"page_size": page_size, "page_count": page_count, "freelist_count": freelist,
                     "free_page_pct": round(100.0 * freelist / page_count, 3) if page_count else 0.0,
                     "file_bytes": os.path.getsize(sqlite_path)}
    return out


def report(jsonl: str, md: str) -> None:
    samples = [json.loads(l) for l in Path(jsonl).read_text(encoding="utf-8").splitlines() if l.strip()]
    lines = ["# Dead tuples and autovacuum (Postgres) vs free pages (SQLite)", "",
             f"Samples: {len(samples)}, from `{jsonl}`.", "",
             "Autovacuum settings: " + ", ".join(f"`{k}={v}`" for k, v in samples[0]["pg_settings"].items()), "",
             "## Postgres, per sample (sum over the day-scoped base tables)", "",
             "| sample | at | live | dead | dead % | deletes | updates | autovacuums | DB bytes |",
             "|---|---|---|---|---|---|---|---|---|"]
    for s in samples:
        live = sum(t["live"] for t in s["pg"].values())
        dead = sum(t["dead"] for t in s["pg"].values())
        pct = 100.0 * dead / (live + dead) if live + dead else 0.0
        lines.append(f"| {s['label']} | {s['at']} | {live:,} | {dead:,} | {pct:.1f} | "
                     f"{sum(t['del'] for t in s['pg'].values()):,} | {sum(t['upd'] for t in s['pg'].values()):,} | "
                     f"{sum(t['autovacuum_count'] for t in s['pg'].values())} | {s['pg_database_bytes']:,} |")
    lines += ["", "## Postgres, per table (first and last sample)", "",
              "| table | sample | live | dead | deletes | autovacuums | last autovacuum | bytes |",
              "|---|---|---|---|---|---|---|---|"]
    for name in TABLES:
        for s in (samples[0], samples[-1]):
            t = s["pg"].get(name)
            if t:
                lines.append(f"| {name} | {s['label']} | {t['live']:,} | {t['dead']:,} | {t['del']:,} | "
                             f"{t['autovacuum_count']} | {t['last_autovacuum'] or '-'} | {t['total_bytes']:,} |")
    lines += ["", "## SQLite working copy (sandbox)", "",
              "| sample | page_count | freelist_count | free % | file bytes |", "|---|---|---|---|---|"]
    for s in samples:
        q = s["sqlite"]
        lines.append(f"| {s['label']} | {q['page_count']:,} | {q['freelist_count']:,} | {q['free_page_pct']} | "
                     f"{q['file_bytes']:,} |")
    Path(md).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1] == "--report":
        report(sys.argv[2], sys.argv[3])
    else:
        sqlite_path, dsn, out, label = sys.argv[1:5]
        s = sample(sqlite_path, dsn, label)
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps(s) + "\n")
        print(json.dumps({"label": label, "dead": sum(t["dead"] for t in s["pg"].values()),
                          "autovacuums": sum(t["autovacuum_count"] for t in s["pg"].values()),
                          "sqlite_free": s["sqlite"]["freelist_count"]}))
