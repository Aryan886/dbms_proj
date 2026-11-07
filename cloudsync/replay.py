"""Replay simulator: a stand-in for the dead Kite feed (spec stories 36-39).

Replays one historical trading day from a SOURCE database (opened read-only)
into a TARGET database that has CDC installed, so the triggers fire exactly as
they would with a live feed. The target must be a throwaway copy (a
`cloudsync sandbox`): the real database and the main working copy are refused.

1. Rewind: the day's rows are deleted from the target's in-scope tables.
2. Replay, in time order, each row released when it would have arrived live
   (a candle when it closes, everything else at its own timestamp):
     * candles  -> utils.db_func.store_market_data (the bot recomputes SL/SH),
     * VIX      -> utils.vix_fetcher.store_vix_data,
     * signals  -> utils.db_func.store_signal,
     * option_data, delta_cache, market_sma_1h rows are inserted verbatim
       (decision D34: the bot's option writer stamps datetime.now(), its delta
       writer calls Kite, and its SMA writer recomputes from the frame it is
       given; all three would change the day's data).
   `speed` = simulated seconds per real second (0 = as fast as possible).
3. Chaos toggles:
     revise  : every 30th 1m candle, the previous minute is re-written with
               close = open (the bot's ON CONFLICT DO UPDATE path);
     rebuild : after the day, the bot's own backfill_market_data_1h deletes and
               rebuilds the 1h candles and their SMAs;
     kill    : the first `sync once` run during the replay is killed mid-batch
               (CLOUDSYNC_FAULT=mid_batch:1); later runs recover.
   With `sync_dsn`, `sync once` runs every `sync_every` replay steps and once
   at the end, as separate processes (like the daemon would).
"""
import contextlib
import os
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from cloudsync.guard import assert_writable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAIN_WORKING_COPY = PROJECT_ROOT / "data" / "trading_bot.db"
_CANDLE_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
_TIMESTAMPED = ["market_data_1m", "market_data_5m", "market_data_15m", "market_data_1h", "market_sma_1h",
                "vix_data", "signals", "option_data", "delta_cache"]
CHAOS = {"revise", "rebuild", "kill"}
_REVISE_EVERY = 30


def _refuse_main_pair(target: Path) -> None:
    assert_writable(target, "replay")
    if Path(target).resolve() == MAIN_WORKING_COPY.resolve():
        raise SystemExit(f"REFUSED: replay writes to {MAIN_WORKING_COPY}, the main working copy. Experiments run "
                         f"on a throwaway pair: `cloudsync sandbox create NAME`, then pass its sqlite path.")


def _day_rows(source: Path, day: str) -> dict[str, list[dict]]:
    conn = sqlite3.connect(f"file:{Path(source).resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        order = {"option_data": "id", "delta_cache": "id", "market_sma_1h": "timestamp, symbol"}
        return {t: [dict(r) for r in conn.execute(
                    f"SELECT * FROM {t} WHERE timestamp >= ? AND timestamp <= ? ORDER BY {order.get(t, 'timestamp')}",
                    (f"{day} 00:00:00", f"{day} 23:59:59"))]
                for t in _TIMESTAMPED}
    finally:
        conn.close()


def _rewind(target: Path, day: str) -> dict[str, int]:
    conn = sqlite3.connect(target, timeout=30)
    try:
        deleted = {t: conn.execute(f"DELETE FROM {t} WHERE timestamp >= ? AND timestamp <= ?",
                                   (f"{day} 00:00:00", f"{day} 23:59:59")).rowcount for t in _TIMESTAMPED}
        conn.commit()
        return deleted
    finally:
        conn.close()


def _timeline(rows: dict[str, list[dict]]) -> list[tuple[datetime, dict[str, list[dict]]]]:
    """Group rows by the moment they would have arrived live."""
    events = defaultdict(lambda: defaultdict(list))
    for table, items in rows.items():
        for r in items:
            ts = datetime.fromisoformat(r["timestamp"])
            if table.startswith("market_data_"):
                ts += timedelta(minutes=_CANDLE_MINUTES[table.removeprefix("market_data_")])
            elif table == "market_sma_1h":
                ts += timedelta(minutes=60)  # written with its hourly candle
            events[ts][table].append(r)
    return sorted(events.items())


def _candles_df(items: list[dict]):
    import pandas as pd
    df = pd.DataFrame(items)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    keep = ["timestamp", "open", "high", "low", "close", "ao_value", "donchian_upper", "donchian_lower",
            "donchian_mid"]
    return df[keep].set_index("timestamp")


def _insert_verbatim(target: Path, table: str, items: list[dict]) -> None:
    cols = [c for c in items[0] if c != "id"]  # new AUTOINCREMENT ids, in source-id order
    verb = "INSERT OR REPLACE" if table == "market_sma_1h" else "INSERT"  # the bot's own verb for SMAs
    conn = sqlite3.connect(target, timeout=30)
    try:
        conn.executemany(f"{verb} INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         [tuple(r[c] for c in cols) for r in items])
        conn.commit()
    finally:
        conn.close()


def _sync(target: Path, dsn: str, fault: str | None) -> dict:
    env = dict(os.environ)
    args = [sys.executable, "-m", "cloudsync", "sync", "once", "--sqlite", str(target), "--dsn", dsn]
    if fault:
        env["CLOUDSYNC_FAULT"] = fault
        args += ["--batch-size", "50"]
    else:
        env.pop("CLOUDSYNC_FAULT", None)
    t0 = time.perf_counter()
    proc = subprocess.run(args, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
    return {"fault": fault, "exit_code": proc.returncode, "seconds": round(time.perf_counter() - t0, 2)}


def run(source: Path, target: Path, day: str, speed: float = 0.0, chaos: set[str] = frozenset(),
        sync_dsn: str | None = None, sync_every: int = 0, symbol: str = "NIFTY50") -> dict:
    unknown = set(chaos) - CHAOS
    if unknown:
        raise SystemExit(f"unknown chaos toggle(s) {sorted(unknown)}; choose from {sorted(CHAOS)}")
    _refuse_main_pair(target)
    conn = sqlite3.connect(f"file:{Path(target).resolve().as_posix()}?mode=ro", uri=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = '_changelog'").fetchone():
            raise SystemExit(f"{target} has no CDC installed: run `cloudsync cdc-install` (or use a sandbox)")
    finally:
        conn.close()

    bot_repo = os.environ.get("BOT_REPO", r"C:\Users\aryan\Desktop\AlgoTrade")
    if bot_repo not in sys.path:
        sys.path.append(bot_repo)
    from utils.db_func import store_market_data, store_signal
    from utils.vix_fetcher import store_vix_data

    rows = _day_rows(source, day)
    if not any(rows.values()):
        raise SystemExit(f"no rows for {day} in {source}")
    summary = {"day": day, "source": str(source), "target": str(target), "chaos": sorted(chaos),
               "rewound": _rewind(target, day), "written": defaultdict(int), "revised": [], "syncs": []}
    db = str(target)
    t_start, written_1m, previous_1m = time.perf_counter(), 0, None
    timeline = _timeline(rows)
    # The bot prints a lot; keep stdout for the JSON summary.
    with contextlib.redirect_stdout(sys.stderr):
        for step, (moment, batch) in enumerate(timeline, start=1):
            for table in ("market_data_1m", "market_data_5m", "market_data_15m", "market_data_1h"):
                if batch.get(table):
                    store_market_data(_candles_df(batch[table]), symbol=symbol,
                                      interval=table.removeprefix("market_data_"), db_path=db)
                    summary["written"][table] += len(batch[table])
            for r in batch.get("market_data_1m", []):
                written_1m += 1
                if "revise" in chaos and previous_1m is not None and written_1m % _REVISE_EVERY == 0:
                    revised = dict(previous_1m, close=previous_1m["open"])
                    store_market_data(_candles_df([revised]), symbol=symbol, interval="1m", db_path=db)
                    summary["revised"].append(previous_1m["timestamp"])
                previous_1m = r
            for r in batch.get("vix_data", []):
                store_vix_data(r["timestamp"], r["symbol"], r["vix_value"], r["vix_ao_value"],
                               r["vix_donchian_upper"], r["vix_donchian_lower"], r["vix_donchian_mid"], db_path=db)
                summary["written"]["vix_data"] += 1
            for r in batch.get("signals", []):
                store_signal(r["timestamp"], r["symbol"], r["signal"], r["reason"], r["confidence_score"],
                             db_path=db)
                summary["written"]["signals"] += 1
            for table in ("market_sma_1h", "option_data", "delta_cache"):
                if batch.get(table):
                    _insert_verbatim(target, table, batch[table])
                    summary["written"][table] += len(batch[table])

            if sync_dsn and sync_every and step % sync_every == 0:
                first = not summary["syncs"]
                summary["syncs"].append(_sync(target, sync_dsn, "mid_batch:1" if first and "kill" in chaos else None))
            if speed > 0 and step < len(timeline):
                time.sleep((timeline[step][0] - moment).total_seconds() / speed)

        if "rebuild" in chaos:
            from utils.market_data_1h import backfill_market_data_1h
            summary["rebuild"] = backfill_market_data_1h(db_path=db)
    if sync_dsn:
        summary["syncs"].append(_sync(target, sync_dsn, None))
        if "kill" in chaos and len(summary["syncs"]) == 1:
            summary["note"] = "kill needs --sync-every so a sync runs during the replay"
    summary["written"] = dict(summary["written"])
    summary["seconds"] = round(time.perf_counter() - t_start, 2)
    conn = sqlite3.connect(f"file:{Path(target).resolve().as_posix()}?mode=ro", uri=True)
    try:
        summary["changelog_backlog"] = conn.execute("SELECT count(*) FROM _changelog").fetchone()[0]
    finally:
        conn.close()
    return summary
