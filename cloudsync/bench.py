"""Benchmark: bot-style writes while a sync-style reader runs, rollback journal vs WAL.

For each journal mode a fresh copy of the database is made (SQLite backup
API), then for `seconds`:
  * a WRITER process inserts one small row and commits, every ~5 ms (the bot
    writing ticks/candles), with the bot's busy handling: Python's sqlite3
    default `timeout` unless overridden;
  * a READER process repeatedly opens a read transaction and scans a large
    table (the sync engine reading a batch snapshot).
Separate processes, so the measurement is SQLite locking, not Python's GIL.

Rollback journal: a writer must take an EXCLUSIVE lock to commit, which waits
for every reader's SHARED lock to go away, and a pending writer blocks new
readers. WAL: readers read a snapshot from the main file + WAL while the writer
appends, so neither waits for the other.
"""
import json
import multiprocessing as mp
import sqlite3
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from cloudsync.guard import assert_writable

WRITE_INTERVAL_S = 0.005


def _copy(src: Path, dst: Path, mode: str) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(f"{dst}{suffix}").unlink(missing_ok=True)
    s = sqlite3.connect(f"file:{src.resolve().as_posix()}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        s.close()
    d.execute(f"PRAGMA journal_mode={mode}")
    d.execute("CREATE TABLE IF NOT EXISTS _bench_writes (id INTEGER PRIMARY KEY, ts TEXT, v REAL)")
    d.commit()
    d.close()


def _writer(path: str, seconds: float, timeout: float, start_at: float, out) -> None:
    conn = sqlite3.connect(path, timeout=timeout)
    latencies, errors = [], 0
    while time.time() < start_at:
        time.sleep(0.001)
    end = start_at + seconds
    while time.time() < end:
        t0 = time.perf_counter()
        try:
            conn.execute("INSERT INTO _bench_writes (ts, v) VALUES (datetime('now'), ?)", (t0,))
            conn.commit()
            latencies.append((time.perf_counter() - t0) * 1000)
        except sqlite3.OperationalError as err:
            if "locked" not in str(err) and "busy" not in str(err):
                raise
            errors += 1
            try:
                conn.rollback()
            except sqlite3.OperationalError:
                pass
        time.sleep(WRITE_INTERVAL_S)
    conn.close()
    out.put(("writer", latencies, errors))


def _reader(path: str, table: str, seconds: float, timeout: float, start_at: float, out) -> None:
    conn = sqlite3.connect(path, timeout=timeout, isolation_level=None)
    durations, errors = [], 0
    while time.time() < start_at:
        time.sleep(0.001)
    end = start_at + seconds
    while time.time() < end:
        t0 = time.perf_counter()
        try:
            conn.execute("BEGIN")
            conn.execute(f'SELECT * FROM "{table}"').fetchall()
            conn.execute("COMMIT")
            durations.append((time.perf_counter() - t0) * 1000)
        except sqlite3.OperationalError as err:
            if "locked" not in str(err) and "busy" not in str(err):
                raise
            errors += 1
            if conn.in_transaction:
                conn.execute("ROLLBACK")
    conn.close()
    out.put(("reader", durations, errors))


def _pct(values, p):
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))], 3)


def _run_mode(db: Path, mode: str, table: str, seconds: float, timeout: float) -> dict:
    ctx = mp.get_context("spawn")
    out = ctx.Queue()
    start_at = time.time() + 1.5  # both processes start together, after interpreter startup
    procs = [ctx.Process(target=_writer, args=(str(db), seconds, timeout, start_at, out)),
             ctx.Process(target=_reader, args=(str(db), table, seconds, timeout, start_at, out))]
    for p in procs:
        p.start()
    results = {role: (values, errors) for role, values, errors in (out.get(timeout=seconds + 120) for _ in procs)}
    for p in procs:
        p.join()
    (w_lat, w_err), (r_dur, r_err) = results["writer"], results["reader"]
    return {
        "journal_mode": mode,
        "writes_ok": len(w_lat), "write_lock_errors": w_err,
        "write_latency_ms": {"p50": _pct(w_lat, 50), "p95": _pct(w_lat, 95), "p99": _pct(w_lat, 99),
                             "max": round(max(w_lat), 3) if w_lat else None,
                             "mean": round(statistics.fmean(w_lat), 3) if w_lat else None},
        "reads_ok": len(r_dur), "read_lock_errors": r_err,
        "read_ms": {"p50": _pct(r_dur, 50), "max": round(max(r_dur), 3) if r_dur else None},
    }


def run(sqlite_path: Path, out_dir: Path, seconds: float, timeout: float, table: str) -> dict:
    assert_writable(out_dir, "bench-wal (database copies and report)")
    out_dir.mkdir(parents=True, exist_ok=True)
    scratch = out_dir / "_bench_tmp"
    scratch.mkdir(exist_ok=True)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "source": str(sqlite_path),
              "seconds_per_mode": seconds, "busy_timeout_s": timeout, "reader_table": table,
              "write_interval_ms": WRITE_INTERVAL_S * 1000, "modes": []}
    for mode in ("delete", "wal"):
        db = scratch / f"bench_{mode}.db"
        _copy(sqlite_path, db, mode)
        report["modes"].append(_run_mode(db, mode, table, seconds, timeout))
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(f"{db}{suffix}").unlink(missing_ok=True)
    scratch.rmdir()
    (out_dir / "wal_benchmark.json").write_text(json.dumps(report, indent=2))
    (out_dir / "wal_benchmark.md").write_text(_markdown(report), encoding="utf-8")
    return report


def _markdown(r: dict) -> str:
    lines = ["# WAL vs rollback-journal concurrency benchmark", "",
             f"- Generated: {r['generated_at']}", f"- Source: `{r['source']}`",
             f"- {r['seconds_per_mode']} s per mode; writer commits one row every {r['write_interval_ms']} ms; "
             f"reader scans `{r['reader_table']}` in a read transaction, back to back; "
             f"busy timeout {r['busy_timeout_s']} s", "",
             "| Journal mode | Writes OK | Write lock errors | Write p50 ms | p95 ms | p99 ms | max ms "
             "| Reads OK | Read lock errors | Read p50 ms |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for m in r["modes"]:
        w = m["write_latency_ms"]
        lines.append(f"| {m['journal_mode']} | {m['writes_ok']} | {m['write_lock_errors']} | {w['p50']} | {w['p95']} "
                     f"| {w['p99']} | {w['max']} | {m['reads_ok']} | {m['read_lock_errors']} | {m['read_ms']['p50']} |")
    return "\n".join(lines) + "\n"
