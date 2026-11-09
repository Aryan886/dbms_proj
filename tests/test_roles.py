"""End-to-end: three least-privilege roles (spec stories 42-43).

Each consumer connects as its role (libpq `options=-c role=...`, the same as a
login that is a member of the role), and Postgres itself enforces what it may
touch. The data reaches Postgres through the normal pipeline first.
"""
import unittest

import psycopg

from tests.support import make_bot_db, make_pg_database, make_tmpdir, run_cli


def as_role(dsn: str, role: str, search_path: str = "public") -> str:
    return psycopg.conninfo.make_conninfo(dsn, options=f"-c role={role} -c search_path={search_path}")


class RolesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmpdir(self)
        self.sqlite = make_bot_db(self.tmp / "trading_bot.db")  # 3 strategies, 8 trades
        self.dsn = make_pg_database(self)
        run_cli("migrate", "--dsn", self.dsn)
        run_cli("bulk-load", "--sqlite", self.sqlite, "--dsn", self.dsn)

    def assert_denied(self, dsn, query):
        with psycopg.connect(dsn) as conn:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege, msg=query):
                conn.execute(query)

    def test_bot_reader_reads_the_compat_views_but_is_denied_writes(self):
        reader = as_role(self.dsn, "bot_reader", "compat")
        with psycopg.connect(reader) as conn:
            # The dashboard's own listing query, unchanged.
            rows = conn.execute("SELECT * FROM dashboard_trade_history ORDER BY entry_ts DESC, id DESC").fetchall()
        self.assertEqual(len(rows), 8)

        # A single-table view is auto-updatable, so only the missing privilege stops this.
        self.assert_denied(reader, "DELETE FROM dashboard_strategy_state")
        self.assert_denied(reader, "UPDATE public.dashboard_trade_history SET qty = 1")
        self.assert_denied(reader, "INSERT INTO public.instruments (symbol, kind) VALUES ('X', 'equity')")
        # Base tables aren't readable either: the bot sees only its compatibility views.
        self.assert_denied(reader, "SELECT count(*) FROM public.candles")

    def test_sync_runs_as_sync_writer_which_cannot_read_the_consumer_views(self):
        from utils.db_func import store_market_data
        from tests.test_bulk_load_reconcile import candles_df
        run_cli("cdc-install", "--sqlite", self.sqlite, "--dsn", self.dsn)
        store_market_data(candles_df("2026-03-27 09:15", [23000.0 + i for i in range(5)]),
                          interval="1m", db_path=str(self.sqlite))

        writer = as_role(self.dsn, "sync_writer")
        run_cli("sync", "once", "--sqlite", self.sqlite, "--dsn", writer)

        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM candles").fetchone()[0], 5)
        self.assert_denied(writer, "SELECT count(*) FROM compat.market_data_1m")
        self.assert_denied(writer, "SELECT count(*) FROM analytics.strategy_pnl_summary")

    def test_analyst_reads_only_the_analytics_views(self):
        analyst = as_role(self.dsn, "analyst", "analytics")
        with psycopg.connect(analyst) as conn:
            conn.execute("SELECT * FROM strategy_pnl_summary").fetchall()
        self.assert_denied(analyst, "SELECT count(*) FROM public.dashboard_trade_history")
        self.assert_denied(analyst, "SELECT count(*) FROM compat.dashboard_trade_history")
        self.assert_denied(as_role(self.dsn, "bot_reader", "compat"),
                           "SELECT count(*) FROM analytics.strategy_pnl_summary")


if __name__ == "__main__":
    unittest.main()
