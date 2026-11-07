"""End-to-end: the Postgres compatibility views stand in for the bot's SQLite tables.

The bot writes through its own functions into a temp SQLite, the data reaches
Postgres through the normal pipeline (migrate, bulk-load), and then the bot's
REAL query shapes are run twice: against SQLite, and against the `compat`
schema in Postgres (search_path = compat, so the table names are unchanged).
Only the parameter placeholder differs (`?` vs `%s`, a driver detail). The
column names, their order and every row must come back the same.
"""
import sqlite3
import unittest
from datetime import date, datetime
from decimal import Decimal

import psycopg

from tests.support import make_bot_db, make_pg_database, make_tmpdir, run_cli
from tests.test_bulk_load_reconcile import candles_df


def _normalize(value):
    """Postgres types -> the text/float shape SQLite returns for the same value."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


class CompatViewTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmpdir(self)
        self.sqlite = make_bot_db(self.tmp / "trading_bot.db")
        self.dsn = make_pg_database(self)
        run_cli("migrate", "--dsn", self.dsn)

    def load(self):
        run_cli("bulk-load", "--sqlite", self.sqlite, "--dsn", self.dsn)

    def sqlite_query(self, query, params=()):
        conn = sqlite3.connect(self.sqlite)
        try:
            cur = conn.execute(query, params)
            return [d[0] for d in cur.description], cur.fetchall()
        finally:
            conn.close()

    def compat_query(self, query, params=()):
        with psycopg.connect(self.dsn, options="-c search_path=compat") as conn:
            cur = conn.execute(query.replace("?", "%s"), params)
            return [d.name for d in cur.description], [tuple(map(_normalize, r)) for r in cur.fetchall()]

    def assert_same_result(self, query, params=(), min_rows=1):
        expected = self.sqlite_query(query, params)
        self.assertGreaterEqual(len(expected[1]), min_rows, "fixture produced too few rows to compare")
        self.assertEqual(self.compat_query(query, params), expected)


class CandleCompatViewTest(CompatViewTestBase):
    def test_latest_candles_query_returns_the_same_rows_from_the_cloud(self):
        from utils.db_func import store_market_data
        store_market_data(candles_df("2026-03-27 09:15", [23000.05 + i for i in range(8)]),
                          interval="1m", db_path=str(self.sqlite))
        self.load()

        # utils.db_func.fetch_market_data(symbol, start, end, interval="1m", limit=200)
        self.assert_same_result(
            "SELECT * FROM market_data_1m WHERE 1=1 AND symbol = ? AND timestamp >= ? AND timestamp <= ? "
            "ORDER BY timestamp DESC LIMIT 200",
            ("NIFTY50", "2026-03-27 09:16:00", "2026-03-27 09:21:00"), min_rows=6)

    def test_backtester_range_query_matches_for_every_timeframe(self):
        from utils.db_func import store_market_data
        from utils.market_data_1h import backfill_market_data_1h
        store_market_data(candles_df("2026-03-27 09:15", [23000.0 + 3 * i for i in range(10)], freq="5min"),
                          interval="5m", db_path=str(self.sqlite))
        store_market_data(candles_df("2026-03-27 09:15", [23000.0 + i for i in range(12)], freq="15min"),
                          interval="15m", db_path=str(self.sqlite))
        backfill_market_data_1h(db_path=str(self.sqlite))  # the bot's own 1h rebuild from 15m
        self.load()

        # backtesting.data_provider.HistoricalDataProvider._load_market_data_interval
        for tf in ("5m", "15m", "1h"):
            with self.subTest(timeframe=tf):
                self.assert_same_result(
                    f"SELECT * FROM market_data_{tf} WHERE symbol = ? AND timestamp >= ? AND timestamp <= ? "
                    "ORDER BY timestamp",
                    ("NIFTY50", "2026-03-27 00:00:00", "2026-03-27 23:59:59"), min_rows=3)

    def test_backtester_hourly_sma_query_matches(self):
        from utils.db_func import store_sma_from_df
        hourly = candles_df("2026-03-26 09:15", [23000.0 + 7 * i for i in range(14)], freq="1h")
        store_sma_from_df(hourly, "NIFTY50", "1h", db_path=str(self.sqlite))  # the bot's SMA writer
        self.load()

        # backtesting.data_provider.HistoricalDataProvider._merge_with_sma_1h
        self.assert_same_result("SELECT * FROM market_sma_1h WHERE symbol = ? ORDER BY timestamp", ("NIFTY50",),
                                min_rows=14)


class VixAndSignalCompatViewTest(CompatViewTestBase):
    def test_vix_and_signal_queries_return_the_same_rows_from_the_cloud(self):
        import pandas as pd
        from utils.db_func import store_signal, store_vix_data_bulk
        store_vix_data_bulk(pd.DataFrame({"vix_value": [13.821043109416733, 14.1, 14.25]},
                                         index=pd.DatetimeIndex(["2026-03-26 15:20:11", "2026-03-27 09:15:40",
                                                                 "2026-03-27 09:16:05"])),
                            "NIFTY50", db_path=str(self.sqlite))
        store_signal("2026-03-27 09:45:00", "NIFTY50", "SELL", "AO crossover below 0", 0.75, db_path=str(self.sqlite))
        store_signal("2026-03-27 10:45:00", "NIFTY50", "BUY", "AO crossover above 0", None, db_path=str(self.sqlite))
        self.load()

        # backtesting.data_provider.HistoricalDataProvider._load_vix_data
        self.assert_same_result("SELECT * FROM vix_data WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                                ("2026-03-26 00:00:00", "2026-03-27 23:59:59"), min_rows=3)
        # No bot code reads signals back; a full ordered read is the natural shape.
        self.assert_same_result("SELECT * FROM signals ORDER BY timestamp", min_rows=2)


class DashboardCompatViewTest(CompatViewTestBase):
    def test_dashboard_listing_queries_return_the_same_rows_from_the_cloud(self):
        # make_bot_db seeds 3 strategies and demo trades through the dashboard's own store.
        self.load()

        # server.dashboard_store.DashboardStore.list_strategies
        self.assert_same_result("""
            SELECT strategy_id, display_name, status, mode, last_started_at, last_stopped_at, updated_at
            FROM dashboard_strategy_state
            ORDER BY CASE strategy_id WHEN 'nifty-options' THEN 1 WHEN 'donchian-options' THEN 2 ELSE 3 END""",
                                min_rows=3)
        # server.dashboard_store.DashboardStore.get_recent_trades (all rows, so every column is compared)
        self.assert_same_result("SELECT * FROM dashboard_trade_history ORDER BY entry_ts DESC, id DESC LIMIT ?",
                                (100,), min_rows=2)


class OptionCompatViewTest(CompatViewTestBase):
    def test_latest_option_and_delta_snapshot_queries_return_the_same_rows_from_the_cloud(self):
        from tests.test_bulk_load_reconcile import BulkLoadReconcileTest
        from utils.db_func import _canonical_option_order_by
        # The bot's own option-chain writer and delta builder (only Kite is faked).
        BulkLoadReconcileTest.write_option_chain(self)
        BulkLoadReconcileTest.build_deltas(self)
        self.load()

        # utils.db_func: latest option snapshot (MAX(timestamp), then that snapshot in canonical order)
        # (an unaliased aggregate's column label is engine-specific; the bot reads fetchone()[0])
        latest = self.sqlite_query("SELECT MAX(timestamp) FROM option_data WHERE symbol = ?", ("NIFTY50",))
        self.assertEqual(self.compat_query("SELECT MAX(timestamp) FROM option_data WHERE symbol = ?",
                                           ("NIFTY50",))[1], latest[1])
        self.assert_same_result("SELECT * FROM option_data WHERE symbol = ? AND timestamp = ? ORDER BY "
                                + _canonical_option_order_by(include_timestamp=True),
                                ("NIFTY50", latest[1][0][0]), min_rows=4)

        # utils.db_func.get_current_delta_from_cache: latest delta snapshot
        latest = self.sqlite_query("SELECT MAX(timestamp) FROM delta_cache WHERE symbol = ?", ("NIFTY50",))
        self.assertEqual(self.compat_query("SELECT MAX(timestamp) FROM delta_cache WHERE symbol = ?",
                                           ("NIFTY50",))[1], latest[1])
        # The bot doesn't order this query, so only the set of rows is the contract.
        self.assert_same_result("SELECT strike_price, option_type, delta, ltp, tradingsymbol, expiry_date "
                                "FROM delta_cache WHERE timestamp = ? AND symbol = ? ORDER BY strike_price, option_type",
                                (latest[1][0][0], "NIFTY50"), min_rows=2)
        # backtesting.data_provider._load_delta_cache (every column)
        self.assert_same_result("SELECT * FROM delta_cache WHERE symbol = ? AND timestamp >= ? AND timestamp <= ? "
                                "ORDER BY timestamp, id", ("NIFTY50", "2000-01-01 00:00:00", "2100-01-01 00:00:00"),
                                min_rows=2)


if __name__ == "__main__":
    unittest.main()
