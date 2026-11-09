"""End-to-end: analytics views read by the `analyst` role (spec stories 47, 49, 50).

Data reaches Postgres through the normal pipeline. Expected values are worked
out by hand in the comments, never recomputed the way the SQL does.
"""
import sqlite3
import unittest
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import psycopg

from tests.support import make_bot_db, make_pg_database, make_tmpdir, run_cli, sqlite_rows
from tests.test_roles import as_role
from tests.test_sync import SyncTestBase

# (exit IST, realized P&L, sub-category, exit reason); all CLOSED, strategy nifty-options.
CLOSED_TRADES = [
    ("2026-03-23 10:00:00", 1000, "a", "target"),
    ("2026-03-23 14:00:00", -400, "b", "stop_loss"),
    ("2026-03-24 11:00:00", -900, "a", "stop_loss"),
    ("2026-03-25 12:00:00", 300, "b", "target"),
    ("2026-03-25 13:00:00", 1500, "a", "eod"),
]


class AnalyticsTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmpdir(self)
        self.sqlite = make_bot_db(self.tmp / "trading_bot.db")
        self.dsn = make_pg_database(self)
        run_cli("migrate", "--dsn", self.dsn)

    def load(self):
        run_cli("bulk-load", "--sqlite", self.sqlite, "--dsn", self.dsn)

    def analyst_rows(self, query, params=None):
        with psycopg.connect(as_role(self.dsn, "analyst", "analytics")) as conn:
            return conn.execute(query, params).fetchall()


class StrategyPnlTest(AnalyticsTestBase):
    def setUp(self):
        super().setUp()
        conn = sqlite3.connect(self.sqlite)
        conn.execute("DELETE FROM dashboard_trade_history")  # the dashboard's seeded demo trades
        for exit_ts, pnl, subcat, reason in CLOSED_TRADES:
            conn.execute("""INSERT INTO dashboard_trade_history (strategy_id, symbol, entry_ts, exit_ts, side, qty,
                                entry_price, exit_price, realized_pnl, status, source, subcat, exit_reason)
                            VALUES ('nifty-options', 'NIFTY26MAR23000CE', ?, ?, 'BUY', 50, 100, ?, ?,
                                    'CLOSED', 'live', ?, ?)""",
                         (exit_ts[:11] + "09:30:00", exit_ts, 100 + pnl / 50, pnl, subcat, reason))
        # An open position has no realized P&L yet and must not count.
        conn.execute("""INSERT INTO dashboard_trade_history (strategy_id, symbol, entry_ts, side, qty, entry_price,
                            status, source, subcat) VALUES ('nifty-options', 'NIFTY26MAR23000CE',
                            '2026-03-25 14:00:00', 'BUY', 50, 100, 'OPEN', 'live', 'a')""")
        conn.commit()
        conn.close()
        self.load()

    def test_daily_and_cumulative_pnl(self):
        self.assertEqual(
            self.analyst_rows("""SELECT trade_day, trades, wins, pnl, cumulative_pnl FROM strategy_daily_pnl
                                 WHERE strategy_id = 'nifty-options' AND source = 'live' ORDER BY trade_day"""),
            [(date(2026, 3, 23), 2, 1, Decimal("600.00"), Decimal("600.00")),
             (date(2026, 3, 24), 1, 0, Decimal("-900.00"), Decimal("-300.00")),
             (date(2026, 3, 25), 2, 2, Decimal("1800.00"), Decimal("1500.00"))])

    def test_summary_has_win_rate_and_max_drawdown(self):
        # Equity after each closed trade: 1000, 600, -300, 0, 1500. Peak 1000 -> trough -300.
        self.assertEqual(
            self.analyst_rows("""SELECT closed_trades, wins, losses, win_rate, total_pnl, max_drawdown
                                 FROM strategy_pnl_summary WHERE strategy_id = 'nifty-options' AND source = 'live'"""),
            [(5, 3, 2, Decimal("0.6000"), Decimal("1500.00"), Decimal("1300.00"))])

    def test_pnl_by_sub_category_and_exit_reason(self):
        self.assertEqual(
            self.analyst_rows("""SELECT dimension, bucket, trades, wins, pnl, win_rate FROM strategy_pnl_breakdown
                                 WHERE strategy_id = 'nifty-options' AND source = 'live'
                                 ORDER BY dimension, bucket"""),
            [("exit_reason", "eod", 1, 1, Decimal("1500.00"), Decimal("1.0000")),
             ("exit_reason", "stop_loss", 2, 0, Decimal("-1300.00"), Decimal("0.0000")),
             ("exit_reason", "target", 2, 2, Decimal("1300.00"), Decimal("1.0000")),
             ("subcat", "a", 3, 2, Decimal("1600.00"), Decimal("0.6667")),
             ("subcat", "b", 2, 1, Decimal("-100.00"), Decimal("0.5000"))])


def ist(day_time):
    return datetime.strptime(day_time, "%Y-%m-%d %H:%M")


class DataQualityTest(AnalyticsTestBase):
    """Market hours are 09:15-15:30 IST; the last 1m candle of a session starts at 15:29."""

    def test_missing_1m_candles_are_reported_as_runs_of_minutes(self):
        from utils.db_func import store_market_data
        from tests.test_bulk_load_reconcile import candles_df
        # 09:15-09:59 (45 candles), then 10:03-15:28 (326 candles): 10:00-10:02 and 15:29 are missing.
        store_market_data(candles_df("2026-03-27 09:15", [23000.0 + i for i in range(45)]),
                          interval="1m", db_path=str(self.sqlite))
        store_market_data(candles_df("2026-03-27 10:03", [23100.0 + i % 50 for i in range(326)]),
                          interval="1m", db_path=str(self.sqlite))
        self.load()

        self.assertEqual(
            self.analyst_rows("""SELECT symbol, trade_day, first_missing, last_missing, missing_minutes
                                 FROM dq_missing_1m_candles ORDER BY first_missing"""),
            [("NIFTY50", date(2026, 3, 27), ist("2026-03-27 10:00"), ist("2026-03-27 10:02"), 3),
             ("NIFTY50", date(2026, 3, 27), ist("2026-03-27 15:29"), ist("2026-03-27 15:29"), 1)])

    def test_vix_gaps_longer_than_ten_minutes_in_market_hours(self):
        from utils.db_func import store_vix_data_bulk
        # 08:50 (pre-open) and 15:45 (after close) are outside market hours and ignored.
        times = ["2026-03-27 08:50", "2026-03-27 09:20", "2026-03-27 09:28"]
        times += [f"2026-03-27 {9 + m // 60:02d}:{m % 60:02d}" for m in range(45, 6 * 60 + 26, 5)]  # 09:45..15:25
        times += ["2026-03-27 15:45"]
        idx = pd.DatetimeIndex(times)
        store_vix_data_bulk(pd.DataFrame({"vix_value": [14.0] * len(idx)}, index=idx), "NIFTY50",
                            db_path=str(self.sqlite))
        self.load()

        # Gaps: open->09:20 5, 09:20->09:28 8, 09:28->09:45 17 (flagged), then 5-minute steps,
        # 15:25->close 5.
        self.assertEqual(self.analyst_rows("SELECT trade_day, gap_from, gap_to, gap_minutes FROM dq_vix_gaps"),
                         [(date(2026, 3, 27), ist("2026-03-27 09:28"), ist("2026-03-27 09:45"), Decimal("17.0"))])

    def test_stale_option_snapshots_gaps_longer_than_five_minutes(self):
        conn = sqlite3.connect(self.sqlite)
        for ts in ("2026-03-27 09:15:30", "2026-03-27 09:17:00", "2026-03-27 09:30:00", "2026-03-27 15:20:00"):
            conn.execute("""INSERT INTO option_data (timestamp, symbol, strike_price, option_type, ltp, iv,
                                expiry_date, spot_price, tradingsymbol, open_interest)
                            VALUES (?, 'NIFTY50', 23000, 'CE', 118.0, 0.21, '2026-03-31', 23010.0,
                                    'NIFTY2633123000CE', 1000)""", (ts,))
        conn.commit()
        conn.close()
        self.load()

        # open->09:15:30 0.5, 09:15:30->09:17 1.5, 09:17->09:30 13 (stale), 09:30->15:20 350 (stale),
        # 15:20->close 10 (stale: the feed stopped early).
        self.assertEqual(
            self.analyst_rows("""SELECT symbol, trade_day, gap_from, gap_to, gap_minutes
                                 FROM dq_stale_option_snapshots ORDER BY gap_from"""),
            [("NIFTY50", date(2026, 3, 27), ist("2026-03-27 09:17"), ist("2026-03-27 09:30"), Decimal("13.0")),
             ("NIFTY50", date(2026, 3, 27), ist("2026-03-27 09:30"), ist("2026-03-27 15:20"), Decimal("350.0")),
             ("NIFTY50", date(2026, 3, 27), ist("2026-03-27 15:20"), ist("2026-03-27 15:30"), Decimal("10.0"))])


class SyncLagTest(SyncTestBase):
    def analyst_rows(self, query, params=None):
        with psycopg.connect(as_role(self.dsn, "analyst", "analytics")) as conn:
            return conn.execute(query, params).fetchall()

    def test_sync_lag_views_show_batches_backlog_last_seq_and_rejects(self):
        conn = sqlite3.connect(self.sqlite)
        for minute, low in ((15, 22995), (16, 23100), (17, 22995), (18, 22995), (19, 22995)):
            # The 09:16 candle has its low above its high: Postgres rejects it.
            conn.execute("""INSERT INTO market_data_1m (timestamp, symbol, open, high, low, close)
                            VALUES (?, 'NIFTY50', 23000, 23005, ?, 23000)""", (f"2026-03-27 09:{minute}:00", low))
        conn.commit()
        conn.close()
        last_seq = sqlite_rows(self.sqlite, "SELECT max(seq) FROM _changelog")[0][0]

        self.sync_once("--batch-size", "2")

        # 5 entries in batches of 2: 2, 2, 1. The bad candle is the 2nd entry, so batch 1 rejects it.
        batches = self.analyst_rows("""SELECT entries, rejected, backlog_after, latency_ms >= 0
                                       FROM sync_batch_log ORDER BY batch_id""")
        self.assertEqual([b[:3] for b in batches], [(2, 1, 3), (2, 0, 1), (1, 0, 0)])
        self.assertTrue(all(b[3] for b in batches))

        self.assertEqual(self.analyst_rows("""SELECT last_seq, status, rejected_rows FROM sync_table_state
                                              WHERE source_table = 'market_data_1m'"""),
                         [(last_seq, "active", 1)])
        self.assertEqual(self.analyst_rows("SELECT source_table, rejected FROM rejected_rows_by_day"),
                         [("market_data_1m", 1)])
        self.assertEqual(self.analyst_rows("""SELECT batches, entries, rejected, backlog_at_end
                                              FROM sync_lag_by_hour"""),
                         [(3, 5, 1, 0)])


if __name__ == "__main__":
    unittest.main()
