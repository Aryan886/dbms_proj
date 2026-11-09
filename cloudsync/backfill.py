"""P&L backfill (spec story 48): fill the cloud's trade history from backtest output.

The bot's unchanged backtester (the same worker as level 3, D42 shim included)
runs on a backup copy of the working copy. Its trades go straight into
Postgres `dashboard_trade_history`, tagged so they can never be mistaken for
the bot's own rows (owner's decision: cloud only, SQLite untouched):

  - source = 'backtest-backfill' and a NEGATIVE id (SQLite ids are never negative, so the
    sync can't overwrite or delete them; a CHECK constraint enforces the pair);
  - the compat view and reconciliation levels 1-2 cover only id > 0, the rows
    that mirror SQLite.

One backtest trade becomes one row, following the bot's own flat trade record
(backtesting.metrics.TradeLog.to_dataframe) for section, subcat, SL and exit reason.
Re-running a window replaces that window's backtest rows (idempotent).
"""
import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from cloudsync import pg
from cloudsync.parity import _copy_sqlite, run_backtest

SOURCE_TAG = "backtest-backfill"


def _row(t: dict, strategy_id: str) -> dict:
    """One backtest trade -> one dashboard_trade_history row (multi-leg trades carry no single contract).

    The backtester's totals are signed net premiums for the whole position (negative = paid, a net
    debit) and its legs carry per-unit prices but no quantity. The multiplier is recovered as
    |entry total| / |net per-unit leg premium| (50 for every trade in the real data), so the row
    keeps the dashboard's identity (exit_price - entry_price) * qty = realized P&L for a debit."""
    legs = t.get("legs") or []
    entry_total = float(t.get("entry_price_total") or 0.0)
    net_unit = sum((1 if leg.get("side") == "BUY" else -1) * float(leg.get("entry_price") or 0) for leg in legs)
    qty = round(abs(entry_total) / abs(net_unit)) if net_unit else 1
    qty = qty or 1
    trails = [h for h in (t.get("sl_history") or [])
              if h.get("trigger") == "TRAIL" and h.get("old_sl") != h.get("new_sl")]
    reason = t.get("reason") or {}
    return {
        "strategy_id": strategy_id,
        "entry_ts": t["entry_time"], "exit_ts": t.get("exit_time"),
        "side": "BUY" if entry_total < 0 else "SELL", "qty": qty,
        "entry_price": round(abs(entry_total) / qty, 2),
        "exit_price": None if t.get("exit_price_total") is None else round(abs(float(t["exit_price_total"])) / qty, 2),
        "realized_pnl": t.get("pnl"),
        "status": "CLOSED" if t.get("exit_time") else "OPEN",
        "position_type": t.get("position_type") or None,
        "section": None if reason.get("section") is None else str(reason["section"]),
        "subcat": reason.get("subcat"),
        "exit_reason": t.get("exit_reason") or None,
        "sl_initial": t.get("sl_initial"), "sl_final": t.get("sl_final"),
        "sl_adjustments": len(trails),
    }


def backfill(sqlite_path: Path, dsn: str, start: str, end: str, bot_repo: str, strategy_id: str = "nifty-options",
             out_dir: Path | None = None, work_dir: Path | None = None) -> dict:
    work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="cloudsync_backfill_"))
    work.mkdir(parents=True, exist_ok=True)
    copy = work / "source_copy.db"
    _copy_sqlite(Path(sqlite_path), copy)  # source opened read-only; the backtester writes only the copy
    run = run_backtest(bot_repo, copy, start, end, work)
    if run.get("error"):
        raise SystemExit(f"backtest refused or crashed: {run['error']}")
    rows = [_row(t, strategy_id) for t in run["trades"]]

    window_from = datetime.combine(date.fromisoformat(start), datetime.min.time())
    window_to = datetime.combine(date.fromisoformat(end) + timedelta(days=1), datetime.min.time())
    with pg.connect(dsn) as conn, conn.transaction():
        nifty = conn.execute("SELECT id FROM instruments WHERE symbol = 'NIFTY50'").fetchone()[0]
        replaced = conn.execute(
            """DELETE FROM dashboard_trade_history
               WHERE source = %s AND id < 0 AND strategy_id = %s AND entry_ts >= %s AND entry_ts < %s""",
            (SOURCE_TAG, strategy_id, window_from, window_to)).rowcount
        next_id = conn.execute("SELECT least(coalesce(min(id), 0), 0) - 1 FROM dashboard_trade_history").fetchone()[0]
        with conn.cursor() as cur:
            for i, r in enumerate(sorted(rows, key=lambda r: r["entry_ts"])):
                cur.execute(
                    """INSERT INTO dashboard_trade_history (id, strategy_id, instrument_id, contract_id, entry_ts,
                           exit_ts, side, qty, entry_price, exit_price, realized_pnl, status, source,
                           position_type, section, subcat, exit_reason, sl_initial, sl_final, sl_adjustments)
                       VALUES (%(id)s, %(strategy_id)s, %(instrument_id)s, NULL, %(entry_ts)s::timestamptz,
                           %(exit_ts)s::timestamptz, %(side)s, %(qty)s, %(entry_price)s, %(exit_price)s,
                           %(realized_pnl)s, %(status)s, %(source)s, %(position_type)s, %(section)s, %(subcat)s,
                           %(exit_reason)s, %(sl_initial)s, %(sl_final)s, %(sl_adjustments)s)""",
                    {**r, "id": next_id - i, "instrument_id": nifty, "source": SOURCE_TAG})
    summary = {"start": start, "end": end, "strategy_id": strategy_id, "backtest_trades": run["num_trades"],
               "backtest_total_pnl": run["total_pnl"], "shims": run.get("shims", []),
               "rows_inserted": len(rows), "rows_replaced": replaced,
               "inserted_pnl": round(sum(float(r["realized_pnl"] or 0) for r in rows), 2), "work_dir": str(work)}
    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"backfill_{start}_{end}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        (out_dir / f"backtest_trades_{start}_{end}.json").write_text(json.dumps(run["trades"], indent=1, default=str),
                                                                    encoding="utf-8")
    return summary
