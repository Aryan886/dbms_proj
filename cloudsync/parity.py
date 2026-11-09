"""Level-3 reconciliation: is the cloud copy a working replacement for the bot?

1. Export: every compatibility view (schema `compat`) is written into a fresh
   SQLite file whose tables are created from the SOURCE's own DDL (same column
   order, types and indexes as the bot's database), rows in source-key order.
2. Fidelity (informational): each exported table is compared with the source
   table row for row (EXCEPT in both directions). Expected differences, such
   as quarantined delta_cache duplicates, show up here and explain a diff.
3. Parity: the bot's UNCHANGED backtester runs on a copy of the source and on
   the export, each in its own process, and the two trade lists are diffed.
   Level 3 passes when the trades are identical.

Bot code never touches the source file: it runs on a backup-API copy, because
the backtester opens its database read-write (CREATE TABLE IF NOT EXISTS).
"""
import json
import math
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg

from cloudsync.guard import assert_writable
from cloudsync.tables import SOURCE_TABLES

_WORKER = Path(__file__).with_name("_backtest_worker.py")
_REL_TOL = _ABS_TOL = 1e-9


def _ro(path: Path) -> str:
    return f"file:{Path(path).resolve().as_posix()}?mode=ro"


def _sqlite_value(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


# ---------- 1. export ----------
def export_compat(dsn: str, source_sqlite: Path, out_path: Path) -> dict:
    """Write the compat views into a new SQLite file shaped like the source. Returns rows per table."""
    assert_writable(out_path, "parity export")
    out_path = Path(out_path)
    if out_path.exists():
        out_path.unlink()
    src = sqlite3.connect(_ro(source_sqlite), uri=True)
    out = sqlite3.connect(out_path)
    counts = {}
    try:
        with psycopg.connect(dsn) as pconn:
            for table in SOURCE_TABLES.values():
                ddl = [sql for (sql,) in src.execute(
                    "SELECT sql FROM sqlite_master WHERE tbl_name = ? AND type IN ('table', 'index') "
                    "AND sql IS NOT NULL ORDER BY type = 'index'", (table.name,))]
                for stmt in ddl:
                    out.execute(stmt)
                order = ", ".join(f'"{c}"' for c in table.key_columns)
                with pconn.cursor(name=f"export_{table.name}") as cur:
                    cur.itersize = 5000
                    cur.execute(f'SELECT * FROM compat."{table.name}" ORDER BY {order}')
                    rows = cur.fetchmany(5000)
                    cols = [d.name for d in cur.description]
                    insert = (f'INSERT INTO "{table.name}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
                              f'VALUES ({", ".join("?" * len(cols))})')
                    n = 0
                    while rows:
                        out.executemany(insert, [tuple(map(_sqlite_value, r)) for r in rows])
                        n += len(rows)
                        rows = cur.fetchmany(5000)
                counts[table.name] = n
        out.commit()
    finally:
        out.close()
        src.close()
    return counts


# ---------- 2. fidelity ----------
def fidelity(source_sqlite: Path, export_sqlite: Path) -> dict:
    conn = sqlite3.connect(_ro(export_sqlite), uri=True)
    try:
        conn.execute("ATTACH DATABASE ? AS src", (_ro(source_sqlite),))
        tables = {}
        for name in SOURCE_TABLES:
            def count(sql):
                return conn.execute(sql).fetchone()[0]
            tables[name] = {
                "source_rows": count(f'SELECT count(*) FROM src."{name}"'),
                "export_rows": count(f'SELECT count(*) FROM main."{name}"'),
                "only_in_source": count(f'SELECT count(*) FROM (SELECT * FROM src."{name}" '
                                        f'EXCEPT SELECT * FROM main."{name}")'),
                "only_in_export": count(f'SELECT count(*) FROM (SELECT * FROM main."{name}" '
                                        f'EXCEPT SELECT * FROM src."{name}")'),
            }
            tables[name]["identical"] = tables[name]["only_in_source"] == tables[name]["only_in_export"] == 0
        return tables
    finally:
        conn.close()


# ---------- 3. parity ----------
def _copy_sqlite(source: Path, dest: Path) -> None:
    assert_writable(dest, "parity source copy")
    src = sqlite3.connect(_ro(source), uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def run_backtest(bot_repo: str, db_path: Path, start: str, end: str, work_dir: Path) -> dict:
    """The unchanged backtester in its own process; cwd is a scratch directory.

    A run the backtester refuses or crashes on (for example BacktestDataCoverageError when
    the data no longer covers the window) is a result, not an infrastructure error: it
    comes back with no trades and its last error line, and level 3 fails on it."""
    # Absolute: the worker's cwd is run_dir, so a relative path would resolve twice.
    run_dir = (Path(work_dir) / f"run_{Path(db_path).stem}").resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "trades.json"
    proc = subprocess.run([sys.executable, "-I", str(_WORKER), bot_repo, str(Path(db_path).resolve()), start, end,
                           str(out)], cwd=run_dir, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    (run_dir / "backtest.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0 or not out.exists():
        lines = [ln for ln in proc.stderr.strip().splitlines() if ln.strip()]
        return {"num_trades": 0, "total_pnl": 0.0, "trades": [], "shims": [],
                "error": lines[-1] if lines else f"exit code {proc.returncode}"}
    return json.loads(out.read_text(encoding="utf-8"))


def _trade_key(t: dict) -> tuple:
    return (t.get("entry_time"), t.get("lot_id"), t.get("position_type"))


def _differences(a, b, path="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            out += _differences(a.get(k), b.get(k), f"{path}.{k}" if path else k)
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: {len(a)} items vs {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _differences(x, y, f"{path}[{i}]")]
    if isinstance(a, float) and isinstance(b, float):
        return [] if math.isclose(a, b, rel_tol=_REL_TOL, abs_tol=_ABS_TOL) else [f"{path}: {a!r} vs {b!r}"]
    return [] if a == b else [f"{path}: {a!r} vs {b!r}"]


# The backtester names each trade with str(uuid.uuid4())[:8] (backtest_bot.py), so the
# id differs between any two runs; every other field is deterministic.
_RUN_SPECIFIC = {"trade_id"}


def diff_trades(source: list[dict], cloud: list[dict]) -> dict:
    """Pair trades by (entry time, lot, position type); report unmatched and changed ones."""
    source = [{k: v for k, v in t.items() if k not in _RUN_SPECIFIC} for t in source]
    cloud = [{k: v for k, v in t.items() if k not in _RUN_SPECIFIC} for t in cloud]
    by_key_cloud = {_trade_key(t): t for t in cloud}
    keys_source = {_trade_key(t) for t in source}
    changed = []
    for t in source:
        other = by_key_cloud.get(_trade_key(t))
        if other is not None:
            diffs = _differences(t, other)
            if diffs:
                changed.append({"trade": list(_trade_key(t)), "differences": diffs[:20]})
    return {
        "only_in_source": [list(_trade_key(t)) for t in source if _trade_key(t) not in by_key_cloud],
        "only_in_cloud": [list(_trade_key(t)) for t in cloud if _trade_key(t) not in keys_source],
        "changed": changed,
    }


def level3(sqlite_path: Path, dsn: str, start: str, end: str, bot_repo: str, work_dir: Path | None = None) -> dict:
    keep = work_dir is not None
    work = Path(work_dir) if keep else Path(tempfile.mkdtemp(prefix="cloudsync_parity_"))
    work.mkdir(parents=True, exist_ok=True)
    try:
        export_path, source_copy = work / "cloud_export.db", work / "source_copy.db"
        exported = export_compat(dsn, sqlite_path, export_path)
        fid = fidelity(sqlite_path, export_path)
        _copy_sqlite(sqlite_path, source_copy)
        # Two independent processes on two separate files: run them side by side.
        with ThreadPoolExecutor(max_workers=2) as pool:
            src_future = pool.submit(run_backtest, bot_repo, source_copy, start, end, work)
            cloud_future = pool.submit(run_backtest, bot_repo, export_path, start, end, work)
            src_run, cloud_run = src_future.result(), cloud_future.result()
        diff = diff_trades(src_run["trades"], cloud_run["trades"])
        identical = not (diff["only_in_source"] or diff["only_in_cloud"] or diff["changed"])
        return {
            "passed": (identical and src_run["num_trades"] == cloud_run["num_trades"]
                       and not src_run.get("error") and not cloud_run.get("error")),
            "shims": sorted(set(src_run.get("shims", [])) | set(cloud_run.get("shims", []))),
            "window": {"start": start, "end": end},
            "source": {"num_trades": src_run["num_trades"], "total_pnl": src_run["total_pnl"],
                       "error": src_run.get("error")},
            "cloud": {"num_trades": cloud_run["num_trades"], "total_pnl": cloud_run["total_pnl"],
                      "error": cloud_run.get("error")},
            "trade_diff": diff,
            "exported_rows": exported,
            "fidelity": fid,
            "work_dir": str(work) if keep else None,
        }
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
