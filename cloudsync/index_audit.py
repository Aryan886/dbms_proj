"""Index audit (spec story 40): EXPLAIN ANALYZE of the bot's real query shapes,
run against the `compat` views, under several index variants.

Each variant's indexes are created inside a transaction, measured, and rolled
back, so the audit never leaves an index behind. It still takes locks while it
runs (CREATE INDEX blocks writes to the table), so it belongs on a sandbox pair.

A measurement, not a pass/fail test (spec: benchmarks aren't automated tests).
"""
import json
import os
import statistics
import sys
from pathlib import Path

import psycopg

from cloudsync import pg

REPEATS = 5

# Extra indexes per variant. "baseline" is the schema as migrated: candles and
# the snapshot tables are reached only through their primary keys.
VARIANTS = {
    "baseline": [],
    "brin_ts": [
        "CREATE INDEX audit_candles_brin ON candles USING brin (ts)",
        "CREATE INDEX audit_chain_brin ON option_chain_snapshots USING brin (ts)",
        "CREATE INDEX audit_delta_brin ON delta_snapshots USING brin (ts)",
    ],
    "btree_ts": [
        "CREATE INDEX audit_candles_ts ON candles (instrument_id, timeframe, ts)",  # same as the PK: control
        "CREATE INDEX audit_chain_ts ON option_chain_snapshots (ts)",
        "CREATE INDEX audit_delta_ts ON delta_snapshots (ts)",
    ],
    "btree_ist_expr": [
        # The compat views expose ts AT TIME ZONE 'Asia/Kolkata' (timezone(text, timestamptz) is IMMUTABLE),
        # so the bot's predicates and ORDER BY are on that expression, not on ts.
        "CREATE INDEX audit_candles_ist ON candles (instrument_id, timeframe, (ts AT TIME ZONE 'Asia/Kolkata'))",
        "CREATE INDEX audit_chain_ist ON option_chain_snapshots (instrument_id, (ts AT TIME ZONE 'Asia/Kolkata'))",
        "CREATE INDEX audit_delta_ist ON delta_snapshots ((ts AT TIME ZONE 'Asia/Kolkata'))",
    ],
    "brin_ist_expr": [
        # BRIN on the same expression the views filter on: the fair B-tree vs BRIN comparison.
        "CREATE INDEX audit_candles_brin_ist ON candles USING brin ((ts AT TIME ZONE 'Asia/Kolkata'))",
        "CREATE INDEX audit_chain_brin_ist ON option_chain_snapshots USING brin ((ts AT TIME ZONE 'Asia/Kolkata'))",
        "CREATE INDEX audit_delta_brin_ist ON delta_snapshots USING brin ((ts AT TIME ZONE 'Asia/Kolkata'))",
    ],
}


def _queries(conn) -> list[tuple[str, str, tuple]]:
    """The bot's query text (utils/db_func.py, backtesting/data_provider.py), with parameters
    taken from the data itself: its latest day and its full range."""
    bot_repo = os.environ.get("BOT_REPO", r"C:\Users\aryan\Desktop\AlgoTrade")
    if bot_repo not in sys.path:
        sys.path.append(bot_repo)
    from utils.db_func import _canonical_option_order_by

    first, last = conn.execute("SELECT min(timestamp), max(timestamp) FROM market_data_1m "
                               "WHERE symbol = 'NIFTY50'").fetchone()
    day_start = last.replace(hour=9, minute=15, second=0)
    opt_max = conn.execute("SELECT MAX(timestamp) FROM option_data WHERE symbol = 'NIFTY50'").fetchone()[0]
    delta_max = conn.execute("SELECT MAX(timestamp) FROM delta_cache WHERE symbol = 'NIFTY50'").fetchone()[0]
    return [
        ("latest 200 candles of the last day (fetch_market_data)",
         "SELECT * FROM market_data_1m WHERE 1=1 AND symbol = %s AND timestamp >= %s AND timestamp <= %s "
         "ORDER BY timestamp DESC LIMIT 200", ("NIFTY50", day_start, last)),
        ("full-range candles for a backtest (data_provider)",
         "SELECT * FROM market_data_1m WHERE symbol = %s AND timestamp >= %s AND timestamp <= %s "
         "ORDER BY timestamp", ("NIFTY50", first, last)),
        ("latest option snapshot time",
         "SELECT MAX(timestamp) FROM option_data WHERE symbol = %s", ("NIFTY50",)),
        ("latest option snapshot rows",
         "SELECT * FROM option_data WHERE symbol = %s AND timestamp = %s ORDER BY "
         + _canonical_option_order_by(include_timestamp=True), ("NIFTY50", opt_max)),
        ("latest delta snapshot time",
         "SELECT MAX(timestamp) FROM delta_cache WHERE symbol = %s", ("NIFTY50",)),
        ("latest delta snapshot rows (get_current_delta_from_cache)",
         "SELECT strike_price, option_type, delta, ltp, tradingsymbol, expiry_date FROM delta_cache "
         "WHERE timestamp = %s AND symbol = %s", (delta_max, "NIFTY50")),
    ]


def _explain(conn, query, params) -> dict:
    times, plan = [], None
    for _ in range(REPEATS):
        plan = conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, params).fetchone()[0][0]
        times.append(plan["Execution Time"])
    top = plan["Plan"]

    def nodes(n):
        yield n
        for child in n.get("Plans", []):
            yield from nodes(child)
    scans = sorted({f"{n['Node Type']}" + (f" using {n['Index Name']}" if "Index Name" in n else "")
                    + (f" on {n['Relation Name']}" if "Relation Name" in n else "")
                    for n in nodes(top) if "Scan" in n["Node Type"]})
    return {"median_ms": round(statistics.median(times), 3), "min_ms": round(min(times), 3),
            "shared_hit": top.get("Shared Hit Blocks", 0), "shared_read": top.get("Shared Read Blocks", 0),
            "rows": top.get("Actual Rows"), "scans": scans, "plan": plan}


def run(dsn: str, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {"repeats": REPEATS, "variants": {}}
    with pg.connect(dsn, options="-c search_path=compat,public") as conn:
        queries = _queries(conn)
        conn.commit()
        for variant, ddl in VARIANTS.items():
            sizes = {}
            with conn.transaction(force_rollback=True):
                for stmt in ddl:
                    conn.execute(stmt)
                    name = stmt.split()[2]
                    sizes[name] = conn.execute("SELECT pg_relation_size(%s::regclass)", (name,)).fetchone()[0]
                if ddl:
                    conn.execute("ANALYZE candles, option_chain_snapshots, delta_snapshots")
                results["variants"][variant] = {
                    "indexes": ddl, "index_bytes": sizes,
                    "queries": {label: _explain(conn, q, p) for label, q, p in queries}}
    (out_dir / "index_audit.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    (out_dir / "index_audit.md").write_text(_markdown(results), encoding="utf-8")
    return results


def _markdown(results: dict) -> str:
    variants = list(results["variants"])
    labels = list(results["variants"]["baseline"]["queries"])
    lines = ["# Index audit: the bot's query shapes on the compat views", "",
             f"Median execution time of {results['repeats']} `EXPLAIN (ANALYZE, BUFFERS)` runs, in ms. "
             "Each variant's indexes are created in a transaction and rolled back.", "",
             "| Query | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
    for label in labels:
        lines.append(f"| {label} | " + " | ".join(
            f"{results['variants'][v]['queries'][label]['median_ms']}" for v in variants) + " |")
    lines += ["", "## Index sizes", "", "| Variant | Index | Bytes |", "|---|---|---|"]
    for v in variants:
        for name, size in results["variants"][v]["index_bytes"].items():
            lines.append(f"| {v} | {name} | {size:,} |")
    lines += ["", "## Plans (scan nodes)", ""]
    for label in labels:
        lines.append(f"**{label}**")
        for v in variants:
            q = results["variants"][v]["queries"][label]
            lines.append(f"- {v}: {'; '.join(q['scans'])} (buffers hit {q['shared_hit']}, read {q['shared_read']},"
                         f" rows {q['rows']})")
        lines.append("")
    return "\n".join(lines)
