"""Read the analytics views as the `analyst` role and write them to a Markdown artifact.

usage: python scripts/analytics_report.py OUT_MD [DSN]   (DSN defaults to $PG_DSN)
"""
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SECTIONS = [
    ("Strategy P&L summary", "SELECT * FROM strategy_pnl_summary ORDER BY strategy_id, source"),
    ("P&L by sub-category and exit reason (backfilled backtest)",
     "SELECT dimension, bucket, trades, wins, pnl, win_rate FROM strategy_pnl_breakdown "
     "WHERE source = 'backtest-backfill' ORDER BY dimension, pnl DESC"),
    ("Daily P&L, backfilled backtest, first 10 and last 5 days",
     "(SELECT * FROM strategy_daily_pnl WHERE source = 'backtest-backfill' ORDER BY trade_day LIMIT 10) UNION ALL "
     "(SELECT * FROM (SELECT * FROM strategy_daily_pnl WHERE source = 'backtest-backfill' ORDER BY trade_day DESC LIMIT 5) x "
     "ORDER BY trade_day)"),
    ("Data quality: missing 1m candles, totals",
     "SELECT count(*) AS runs, coalesce(sum(missing_minutes), 0) AS minutes, count(DISTINCT trade_day) AS days "
     "FROM dq_missing_1m_candles"),
    ("Data quality: the 10 longest runs of missing 1m candles",
     "SELECT * FROM dq_missing_1m_candles ORDER BY missing_minutes DESC, first_missing LIMIT 10"),
    ("Data quality: stale option snapshots (gap > 5 min)",
     "SELECT * FROM dq_stale_option_snapshots ORDER BY gap_minutes DESC LIMIT 10"),
    ("Data quality: VIX gaps (> 10 min), totals",
     "SELECT count(*) AS gaps, count(DISTINCT trade_day) AS days, max(gap_minutes) AS longest FROM dq_vix_gaps"),
    ("Data quality: the 10 longest VIX gaps", "SELECT * FROM dq_vix_gaps ORDER BY gap_minutes DESC LIMIT 10"),
    ("Sync: per-table state", "SELECT * FROM sync_table_state ORDER BY source_table"),
    ("Sync: lag by hour (last 5 hours with batches)",
     "SELECT * FROM (SELECT * FROM sync_lag_by_hour ORDER BY hour DESC LIMIT 5) x ORDER BY hour"),
    ("Rejected rows by day", "SELECT * FROM rejected_rows_by_day ORDER BY day, source_table"),
]


def fmt(v):
    if isinstance(v, float):
        return f"{v:.2f}"
    return "" if v is None else str(v)


def main(out, dsn=None):
    dsn = psycopg.conninfo.make_conninfo(dsn or os.environ["PG_DSN"],
                                         options="-c role=analyst -c search_path=analytics")
    lines = ["# Analytics views on the main cloud, read as `analyst`", ""]
    with psycopg.connect(dsn) as conn:
        conn.execute("SET TIME ZONE 'Asia/Kolkata'")
        lines.append(f"Role: `{conn.execute('SELECT current_user').fetchone()[0]}`")
        for title, query in SECTIONS:
            cur = conn.execute(query)
            cols = [d.name for d in cur.description]
            rows = cur.fetchall()
            lines += ["", f"## {title}", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
            lines += ["| " + " | ".join(fmt(v) for v in r) + " |" for r in rows]
            if not rows:
                lines.append("| (no rows) |" + " |" * (len(cols) - 1))
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
