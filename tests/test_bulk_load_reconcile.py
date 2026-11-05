"""End-to-end: bot-written SQLite -> migrate -> bulk-load -> reconcile (levels 1-2).

Asserts on the reconciliation report (the deliverable) and, until the
compatibility views land on day 3, on the Postgres base tables.
"""
import json
import unittest
from decimal import Decimal

import pandas as pd

from tests.support import make_bot_db, make_pg_database, make_tmpdir, pg_rows, run_cli, sqlite_rows


def candles_df(start, closes, freq="1min"):
    idx = pd.date_range(start, periods=len(closes), freq=freq)
    return pd.DataFrame(
        {"open": closes, "high": [c + 5 for c in closes], "low": [c - 5 for c in closes], "close": closes},
        index=idx,
    )


class BulkLoadReconcileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmpdir(self)
        self.sqlite = make_bot_db(self.tmp / "trading_bot.db")
        self.dsn = make_pg_database(self)
        self.report_dir = self.tmp / "report"
        run_cli("migrate", "--dsn", self.dsn)

    def load_and_reconcile(self, levels="1,2"):
        run_cli("bulk-load", "--sqlite", self.sqlite, "--dsn", self.dsn)
        proc = run_cli("reconcile", "--sqlite", self.sqlite, "--dsn", self.dsn,
                       "--levels", levels, "--out", self.report_dir, check=False)
        report = json.loads((self.report_dir / "reconciliation.json").read_text())
        return proc, report

    def test_bot_candles_load_and_level1_counts_match(self):
        from utils.db_func import store_market_data
        store_market_data(candles_df("2026-03-27 09:15", [23000.05, 23010.10]),
                          symbol="NIFTY50", interval="1m", db_path=str(self.sqlite))

        proc, report = self.load_and_reconcile(levels="1")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(report["passed"])
        row = report["levels"]["1"]["tables"]["market_data_1m"]
        self.assertEqual((row["sqlite"], row["postgres"], row["rejected"], row["passed"]), (2, 2, 0, True))
        self.assertEqual(
            pg_rows(self.dsn, """
                SELECT i.symbol, c.timeframe, to_char(c.ts AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD HH24:MI:SS'), c.close
                FROM candles c JOIN instruments i ON i.id = c.instrument_id ORDER BY c.ts"""),
            [("NIFTY50", "1m", "2026-03-27 09:15:00", Decimal("23000.05")),
             ("NIFTY50", "1m", "2026-03-27 09:16:00", Decimal("23010.10"))],
        )

    def test_level2_daily_checksums_pass_then_pinpoint_a_corrupted_day(self):
        from utils.db_func import store_market_data
        store_market_data(candles_df("2026-03-26 15:28", [23000.0, 23001.0]), interval="1m", db_path=str(self.sqlite))
        store_market_data(candles_df("2026-03-27 09:15", [23100.0, 23102.5, 23104.0]), interval="1m", db_path=str(self.sqlite))

        proc, report = self.load_and_reconcile(levels="1,2")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        l2 = report["levels"]["2"]["tables"]["market_data_1m"]
        self.assertTrue(l2["passed"])
        self.assertEqual(l2["days_compared"], 2)
        self.assertEqual(l2["mismatches"], [])

        # Simulate silent corruption of one cloud candle on 27 March.
        corrupted = pg_rows(self.dsn, "UPDATE candles SET close = close + 0.05 "
                                      "WHERE ts = '2026-03-27 09:16:00+05:30' RETURNING 1")
        self.assertEqual(len(corrupted), 1)
        proc = run_cli("reconcile", "--sqlite", self.sqlite, "--dsn", self.dsn,
                       "--levels", "2", "--out", self.report_dir, check=False)
        report = json.loads((self.report_dir / "reconciliation.json").read_text())

        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(report["passed"])
        mismatches = report["levels"]["2"]["tables"]["market_data_1m"]["mismatches"]
        self.assertEqual([m["day"] for m in mismatches], ["2026-03-27"])
        self.assertAlmostEqual(mismatches[0]["sqlite"]["sum"], 69306.5)
        self.assertAlmostEqual(mismatches[0]["postgres"]["sum"], 69306.55)
        self.assertTrue((self.report_dir / "reconciliation.md").exists())

    def assert_table_reconciles(self, report, table, expected_rows):
        l1 = report["levels"]["1"]["tables"][table]
        self.assertEqual((l1["sqlite"], l1["postgres"], l1["rejected"]), (expected_rows, expected_rows, 0), l1)
        l2 = report["levels"]["2"]["tables"][table]
        self.assertEqual(l2["mismatches"], [])
        self.assertTrue(l2["passed"])

    def test_vix_observations_load_and_reconcile(self):
        from utils.db_func import store_vix_data_bulk
        idx = pd.DatetimeIndex(["2026-03-26 15:20:11", "2026-03-27 09:15:40", "2026-03-27 09:16:05"])
        store_vix_data_bulk(pd.DataFrame({"vix_value": [13.821043109416733, 14.1, 14.25]}, index=idx),
                            "NIFTY50", db_path=str(self.sqlite))

        proc, report = self.load_and_reconcile()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assert_table_reconciles(report, "vix_data", 3)
        self.assertEqual(report["levels"]["2"]["tables"]["vix_data"]["days_compared"], 2)
        # Computed floats survive bit-for-bit (split typing: double precision).
        self.assertEqual(pg_rows(self.dsn, "SELECT value FROM vix_observations ORDER BY ts LIMIT 1"),
                         [(13.821043109416733,)])

    def test_signals_load_and_reconcile(self):
        from utils.db_func import store_signal
        store_signal("2026-03-26 09:45:00", "NIFTY50", "SELL", "AO crossover below 0", 0.75, db_path=str(self.sqlite))
        store_signal("2026-03-27 13:10:00", "NIFTY50", "BUY", "AO crossover above 0", 0.75, db_path=str(self.sqlite))

        proc, report = self.load_and_reconcile()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assert_table_reconciles(report, "signals", 2)
        self.assertEqual(
            pg_rows(self.dsn, "SELECT s.id, i.symbol, s.signal FROM signals s "
                              "JOIN instruments i ON i.id = s.instrument_id ORDER BY s.id"),
            [(1, "NIFTY50", "SELL"), (2, "NIFTY50", "BUY")],
        )

    def write_option_chain(self, spot=23006.35):
        """Two strikes x CE/PE through the bot's option-chain writer (expiry must be within 14 days)."""
        from datetime import date, timedelta
        from utils.db_func import store_high_accuracy_options_data
        expiry = date.today() + timedelta(days=6)
        options = [
            {"strike_price": strike, "option_type": ot, "ltp": ltp, "iv": 0.2721400525050547,
             "expiry_date": expiry.isoformat(), "tradingsymbol": f"NIFTY{expiry:%y%m%d}{strike}{ot}",
             "open_interest": 4970160}
            for strike, ot, ltp in [(23000, "CE", 121.19999999999999), (23000, "PE", 108.575),
                                    (23050, "CE", 95.4), (23050, "PE", 140.05)]
        ]
        store_high_accuracy_options_data(options, "NIFTY50", spot, db_path=str(self.sqlite))
        return expiry

    def test_option_snapshots_load_with_contract_master_and_reconcile(self):
        expiry = self.write_option_chain()

        proc, report = self.load_and_reconcile()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assert_table_reconciles(report, "option_data", 4)
        contracts = pg_rows(self.dsn, """
            SELECT i.symbol, oc.expiry_date, oc.strike, oc.option_type, oc.tradingsymbol, oc.expiry_source
            FROM option_contracts oc JOIN instruments i ON i.id = oc.instrument_id
            WHERE oc.expiry_source = 'observed' ORDER BY oc.strike, oc.option_type""")
        self.assertEqual(len(contracts), 4)
        self.assertEqual(contracts[0], ("NIFTY50", expiry, 23000, "CE", f"NIFTY{expiry:%y%m%d}23000CE", "observed"))

    def build_deltas(self, spot=23006.35):
        """Run the bot's delta builder; only the dead Kite API is faked."""
        import sys
        import types
        from unittest.mock import patch
        from utils.db_func import calculate_and_store_high_accuracy_delta

        class FakeKite:
            def quote(self, symbol):
                return {symbol: {"last_price": spot}}

        fake_module = types.ModuleType("broker.zerodha_client")
        fake_module.kite_from_saved_token = lambda: FakeKite()
        with patch.dict(sys.modules, {"broker.zerodha_client": fake_module}), \
             patch("utils.vix_fetcher.fetch_live_option_chain", return_value=[]):
            result = calculate_and_store_high_accuracy_delta("NIFTY50", db_path=str(self.sqlite))
        self.assertIsNotNone(result)

    def test_delta_snapshots_load_and_reconcile(self):
        self.write_option_chain()
        self.build_deltas()
        written = sqlite_rows(self.sqlite, "SELECT count(*) FROM delta_cache")[0][0]
        self.assertGreater(written, 0)

        proc, report = self.load_and_reconcile()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assert_table_reconciles(report, "delta_cache", written)

    def test_dashboard_tables_load_with_derived_contracts_and_reconcile(self):
        # make_bot_db() already ran DashboardStore.initialize(): 3 strategies, 8 seeded trades.
        proc, report = self.load_and_reconcile()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assert_table_reconciles(report, "dashboard_strategy_state", 3)
        self.assert_table_reconciles(report, "dashboard_trade_history", 8)
        from datetime import date
        self.assertEqual(
            pg_rows(self.dsn, """
                SELECT t.id, i.symbol, oc.tradingsymbol, oc.expiry_date, oc.strike, oc.option_type,
                       oc.expiry_source, t.exit_ts IS NULL
                FROM dashboard_trade_history t
                JOIN instruments i ON i.id = t.instrument_id
                JOIN option_contracts oc ON oc.id = t.contract_id
                WHERE t.id IN (1, 8) ORDER BY t.id"""),
            [(1, "NIFTY50", "NIFTY26MAY22400PE", date(2026, 5, 26), 22400, "PE", "derived", False),
             (8, "NIFTY50", "NIFTY26MAY22550CE", date(2026, 5, 26), 22550, "CE", "derived", True)],
        )

    def test_weekly_trade_symbol_reuses_the_observed_contract(self):
        expiry = self.write_option_chain()
        weekly = f"NIFTY{expiry:%y}{'123456789OND'[expiry.month - 1]}{expiry:%d}23000CE"
        observed = f"NIFTY{expiry:%y%m%d}23000CE"
        import sqlite3
        conn = sqlite3.connect(self.sqlite)
        conn.execute("""INSERT INTO dashboard_trade_history (strategy_id, symbol, entry_ts, side, qty,
                        entry_price, status, source) VALUES ('nifty-options', ?, '2026-03-27 10:00:00',
                        'SELL', 50, 120.5, 'OPEN', 'live-sync')""", (weekly,))
        conn.commit()
        conn.close()

        proc, report = self.load_and_reconcile()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assert_table_reconciles(report, "dashboard_trade_history", 9)
        # Weekly symbol parses to the same natural key as the observed contract: one contract, not two.
        self.assertEqual(
            pg_rows(self.dsn, """SELECT oc.tradingsymbol, oc.expiry_source FROM dashboard_trade_history t
                                 JOIN option_contracts oc ON oc.id = t.contract_id WHERE t.id = 9"""),
            [(observed, "observed")],
        )

    def test_constraint_violating_candle_is_quarantined_not_lost(self):
        from utils.db_func import store_market_data
        good = candles_df("2026-03-27 09:15", [23000.0, 23001.0, 23002.0])
        good.iloc[1, good.columns.get_loc("low")] = 23100.0  # low above high: impossible candle
        store_market_data(good, interval="1m", db_path=str(self.sqlite))

        proc, report = self.load_and_reconcile()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        l1 = report["levels"]["1"]["tables"]["market_data_1m"]
        self.assertEqual((l1["sqlite"], l1["postgres"], l1["rejected"], l1["passed"]), (3, 2, 1, True))
        self.assertTrue(report["levels"]["2"]["tables"]["market_data_1m"]["passed"])
        rejected = pg_rows(self.dsn, """SELECT source_table, source_pk, violated_constraint,
                                               raw_row->>'timestamp', (raw_row->>'low')::float8
                                        FROM rejected_rows""")
        self.assertEqual(len(rejected), 1)
        table, pk, constraint, ts, low = rejected[0]
        self.assertEqual((table, pk, ts, low), ("market_data_1m", "2", "2026-03-27 09:16:00", 23100.0))
        self.assertIn(constraint, {"candles_ohlc_low_le_high", "candles_ohlc_open_in_range",
                                   "candles_ohlc_close_in_range"})

    def test_delta_cache_duplicates_keep_highest_id_and_quarantine_the_rest(self):
        import sqlite3
        self.write_option_chain()
        self.build_deltas()
        originals = sqlite_rows(self.sqlite, "SELECT count(*) FROM delta_cache")[0][0]
        # Historical state: older bot versions wrote the same (contract, ts) twice.
        conn = sqlite3.connect(self.sqlite)
        conn.execute("""
            INSERT INTO delta_cache (timestamp, strike_price, option_type, delta, expiry_date,
                                     spot_price, symbol, ltp, tradingsymbol)
            SELECT timestamp, strike_price, option_type, delta + 1.5, expiry_date,
                   spot_price, symbol, ltp, tradingsymbol
            FROM delta_cache ORDER BY id""")
        conn.commit()
        conn.close()

        proc, report = self.load_and_reconcile()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        l1 = report["levels"]["1"]["tables"]["delta_cache"]
        self.assertEqual((l1["sqlite"], l1["postgres"], l1["rejected"], l1["passed"]),
                         (2 * originals, originals, originals, True))
        self.assertTrue(report["levels"]["2"]["tables"]["delta_cache"]["passed"])
        # Survivors are exactly the later copies (highest source id per group)...
        survivors = pg_rows(self.dsn, "SELECT min(source_id), max(source_id) FROM delta_snapshots")[0]
        self.assertEqual(survivors, (originals + 1, 2 * originals))
        # ...and every quarantined row is an original, named as a duplicate of its survivor.
        rejected = pg_rows(self.dsn, """SELECT min(source_pk::int), max(source_pk::int),
                                               count(DISTINCT violated_constraint)
                                        FROM rejected_rows WHERE source_table = 'delta_cache'""")[0]
        self.assertEqual(rejected, (1, originals, 1))

    def test_option_chain_spot_is_stored_once_per_snapshot(self):
        self.write_option_chain(spot=23006.35)

        proc, report = self.load_and_reconcile()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assert_table_reconciles(report, "option_data", 4)
        self.assertEqual(
            pg_rows(self.dsn, """SELECT h.spot_price, count(s.*) FROM option_chain_snapshots h
                                 JOIN option_snapshots s ON s.chain_snapshot_id = h.id GROUP BY h.id"""),
            [(Decimal("23006.35"), 4)],
        )

    def test_option_row_contradicting_its_snapshot_spot_is_quarantined(self):
        import sqlite3
        self.write_option_chain(spot=23006.35)
        conn = sqlite3.connect(self.sqlite)
        conn.execute("""INSERT INTO option_data (timestamp, symbol, strike_price, option_type, ltp, iv,
                                                 expiry_date, spot_price, tradingsymbol, open_interest)
                        SELECT timestamp, symbol, 23100, 'CE', 70.0, 0.2, expiry_date, 23999.0,
                               'NIFTYTEST23100CE', 10
                        FROM option_data LIMIT 1""")
        conn.commit()
        conn.close()

        proc, report = self.load_and_reconcile()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        l1 = report["levels"]["1"]["tables"]["option_data"]
        self.assertEqual((l1["sqlite"], l1["postgres"], l1["rejected"], l1["passed"]), (5, 4, 1, True))
        self.assertEqual(pg_rows(self.dsn, "SELECT source_pk, violated_constraint FROM rejected_rows"),
                         [("5", "option_chain_snapshots_spot_fd")])


if __name__ == "__main__":
    unittest.main()
