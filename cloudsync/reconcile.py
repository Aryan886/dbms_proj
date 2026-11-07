"""Reconciliation between the SQLite source and the Postgres cloud copy.

Level 1: row counts per table. A table passes when every source row is
         accounted for: sqlite_count == postgres_count + rejected_count.
Level 3: parity. The compatibility views are exported to a fresh SQLite file,
         the bot's unchanged backtester runs on the source and on the export,
         and the trade lists are diffed (see cloudsync/parity.py).
Level 2: per-day checksums (count, sum of the table's measure column, min/max
         timestamp) on the IST calendar day. Rows quarantined in rejected_rows
         are excluded from the SQLite side, so a pass means every row that was
         accepted arrived intact, and any mismatch names the day to inspect.
"""
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cloudsync import parity, pg
from cloudsync.tables import SOURCE_TABLES, SourceTable

# Float sums of the same values can differ in the last bits depending on
# summation order; anything beyond this is a real difference.
_REL_TOL, _ABS_TOL = 1e-9, 1e-6


def _sqlite(sqlite_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(sqlite_path).resolve().as_posix()}?mode=ro", uri=True)


def _rejected_pks(conn, table: str) -> list[str]:
    return [pk for (pk,) in conn.execute(
        "SELECT source_pk FROM rejected_rows WHERE source_table = %s AND source_pk IS NOT NULL", (table,))]


def level1(sqlite_path: Path, conn) -> dict:
    tables = {}
    src_conn = _sqlite(sqlite_path)
    try:
        for t in SOURCE_TABLES.values():
            src = src_conn.execute(f'SELECT count(*) FROM "{t.name}"').fetchone()[0]
            dst = conn.execute(t.pg_count_sql).fetchone()[0]
            rej = conn.execute("SELECT count(*) FROM rejected_rows WHERE source_table = %s", (t.name,)).fetchone()[0]
            tables[t.name] = {"sqlite": src, "postgres": dst, "rejected": rej, "passed": src == dst + rej}
    finally:
        src_conn.close()
    return {"passed": all(v["passed"] for v in tables.values()), "tables": tables}


def _sqlite_daily(src_conn, t: SourceTable, excluded: list[str]) -> dict:
    src_conn.execute("CREATE TEMP TABLE IF NOT EXISTS _excluded (pk TEXT PRIMARY KEY)")
    src_conn.execute("DELETE FROM _excluded")
    src_conn.executemany("INSERT OR IGNORE INTO _excluded VALUES (?)", [(pk,) for pk in excluded])
    rows = src_conn.execute(f"""
        SELECT substr({t.ts_col}, 1, 10), count(*), total({t.measure_col}),
               substr(min({t.ts_col}), 1, 19), substr(max({t.ts_col}), 1, 19)
        FROM "{t.name}"
        WHERE CAST({t.key_sql()} AS TEXT) NOT IN (SELECT pk FROM _excluded)
        GROUP BY 1 ORDER BY 1""").fetchall()
    return {r[0]: r[1:] for r in rows}


def _same(a, b) -> bool:
    count_a, sum_a, min_a, max_a = a
    count_b, sum_b, min_b, max_b = b
    return (count_a == count_b and min_a == min_b and max_a == max_b
            and math.isclose(sum_a or 0.0, sum_b or 0.0, rel_tol=_REL_TOL, abs_tol=_ABS_TOL))


def _as_dict(v):
    if v is None:
        return None
    return {"count": v[0], "sum": v[1], "min_ts": v[2], "max_ts": v[3]}


def level2(sqlite_path: Path, conn) -> dict:
    tables = {}
    src_conn = _sqlite(sqlite_path)
    try:
        for t in SOURCE_TABLES.values():
            src = _sqlite_daily(src_conn, t, _rejected_pks(conn, t.name))
            dst = {r[0]: r[1:] for r in conn.execute(t.pg_daily_sql)}
            mismatches = []
            for day in sorted(set(src) | set(dst)):
                a, b = src.get(day), dst.get(day)
                if a is None or b is None or not _same(a, b):
                    mismatches.append({"day": day, "sqlite": _as_dict(a), "postgres": _as_dict(b)})
            tables[t.name] = {"passed": not mismatches, "days_compared": len(set(src) | set(dst)),
                              "measure": t.measure_col, "mismatches": mismatches}
    finally:
        src_conn.close()
    return {"passed": all(v["passed"] for v in tables.values()), "tables": tables}


def _markdown(report: dict) -> str:
    verdict = lambda ok: "PASS" if ok else "FAIL"  # noqa: E731
    lines = [f"# Reconciliation report — {verdict(report['passed'])}", "",
             f"- Generated: {report['generated_at']}", f"- SQLite source: `{report['sqlite']}`", ""]
    if "1" in report["levels"]:
        l1 = report["levels"]["1"]
        lines += [f"## Level 1 — row counts: {verdict(l1['passed'])}", "",
                  "| Table | SQLite | Postgres | Rejected | Result |", "|---|---:|---:|---:|---|"]
        for name, v in l1["tables"].items():
            lines.append(f"| {name} | {v['sqlite']} | {v['postgres']} | {v['rejected']} | {verdict(v['passed'])} |")
        lines.append("")
    if "2" in report["levels"]:
        l2 = report["levels"]["2"]
        lines += [f"## Level 2 — per-day checksums: {verdict(l2['passed'])}", "",
                  "| Table | Measure | Days | Mismatched days | Result |", "|---|---|---:|---:|---|"]
        for name, v in l2["tables"].items():
            lines.append(f"| {name} | {v['measure']} | {v['days_compared']} | {len(v['mismatches'])} | {verdict(v['passed'])} |")
        for name, v in l2["tables"].items():
            if v["mismatches"]:
                lines += ["", f"### {name}: differences", "", "| Day | SQLite | Postgres |", "|---|---|---|"]
                for m in v["mismatches"]:
                    lines.append(f"| {m['day']} | {m['sqlite']} | {m['postgres']} |")
        lines.append("")
    if "3" in report["levels"]:
        l3 = report["levels"]["3"]
        diff = l3["trade_diff"]
        lines += [f"## Level 3 — backtest parity: {verdict(l3['passed'])}", "",
                  f"Window {l3['window']['start']} → {l3['window']['end']}. The bot's backtester ran on a copy of the "
                  "source and on a SQLite export of the Postgres compatibility views.", "",
                  "| Run | Trades | Total P&L |", "|---|---:|---:|",
                  f"| Source (SQLite) | {l3['source']['num_trades']} | {l3['source']['total_pnl']:.2f} |",
                  f"| Cloud (export of `compat`) | {l3['cloud']['num_trades']} | {l3['cloud']['total_pnl']:.2f} |", "",
                  *[f"- **The {side} run did not complete:** `{l3[side]['error']}`"
                    for side in ("source", "cloud") if l3[side].get("error")],
                  f"- Trades only in the source run: {len(diff['only_in_source'])}",
                  f"- Trades only in the cloud run: {len(diff['only_in_cloud'])}",
                  f"- Trades in both with different values: {len(diff['changed'])}"]
        if l3.get("shims"):
            lines.append(f"- Backtester shim (decision D42, applied to both runs): `{'; '.join(l3['shims'])}`")
        for label, key in (("only in the source run", "only_in_source"), ("only in the cloud run", "only_in_cloud")):
            if diff[key]:
                lines += ["", f"### Trades {label}", "", "| Entry time | Lot | Type |", "|---|---|---|"]
                lines += [f"| {k[0]} | {k[1]} | {k[2]} |" for k in diff[key]]
        if diff["changed"]:
            lines += ["", "### Trades with different values", ""]
            for c in diff["changed"]:
                lines.append(f"- `{c['trade'][0]}` lot {c['trade'][1]}: " + "; ".join(c["differences"][:5]))
        lines += ["", "### Export fidelity (source table vs exported view, row for row)", "",
                  "| Table | Source rows | Export rows | Only in source | Only in export | Identical |",
                  "|---|---:|---:|---:|---:|---|"]
        for name, f in l3["fidelity"].items():
            lines.append(f"| {name} | {f['source_rows']} | {f['export_rows']} | {f['only_in_source']} | "
                         f"{f['only_in_export']} | {'yes' if f['identical'] else 'no'} |")
        lines.append("")
    return "\n".join(lines)


def run(sqlite_path: Path, dsn: str, levels: list[int], out_dir: Path, start: str | None = None,
        end: str | None = None, parity_dir: Path | None = None) -> dict:
    if 3 in levels and not (start and end):
        raise SystemExit("level 3 needs a backtest window: --start YYYY-MM-DD --end YYYY-MM-DD")
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "sqlite": str(sqlite_path), "levels": {}}
    with pg.connect(dsn) as conn:
        if 1 in levels:
            report["levels"]["1"] = level1(sqlite_path, conn)
        if 2 in levels:
            report["levels"]["2"] = level2(sqlite_path, conn)
    if 3 in levels:
        bot_repo = os.environ.get("BOT_REPO") or _DEFAULT_BOT_REPO
        report["levels"]["3"] = parity.level3(sqlite_path, dsn, start, end, bot_repo, parity_dir)
    report["passed"] = all(lvl["passed"] for lvl in report["levels"].values())
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reconciliation.json").write_text(json.dumps(report, indent=2))
    (out_dir / "reconciliation.md").write_text(_markdown(report), encoding="utf-8")
    return report
