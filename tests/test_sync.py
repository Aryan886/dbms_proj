"""End-to-end: CDC triggers on the bot's SQLite -> `sync once` / `sync daemon` -> Postgres.

Production order is followed in every test: migrate, install CDC (WAL +
changelog + triggers + fingerprints), bulk-load the baseline, then let the bot
write and sync. Assertions are on what reaches Postgres and on the
reconciliation report, never on internal mapping code.
"""
import json
import sqlite3
import unittest
from decimal import Decimal

from tests.support import (TcpForwarder, dsn_via_port, free_port, make_bot_db, make_pg_database, make_tmpdir,
                           pg_rows, run_cli, sqlite_rows)
from tests.test_bulk_load_reconcile import candles_df


class SyncTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmpdir(self)
        self.sqlite = make_bot_db(self.tmp / "trading_bot.db")
        self.dsn = make_pg_database(self)
        self.report_dir = self.tmp / "report"
        run_cli("migrate", "--dsn", self.dsn)
        run_cli("cdc-install", "--sqlite", self.sqlite, "--dsn", self.dsn)
        run_cli("bulk-load", "--sqlite", self.sqlite, "--dsn", self.dsn)

    def sync_once(self, *extra, env=None, check=True):
        proc = run_cli("sync", "once", "--sqlite", self.sqlite, "--dsn", self.dsn, *extra, env=env, check=check)
        return proc

    def reconcile(self, levels="1,2"):
        proc = run_cli("reconcile", "--sqlite", self.sqlite, "--dsn", self.dsn,
                       "--levels", levels, "--out", self.report_dir, check=False)
        report = json.loads((self.report_dir / "reconciliation.json").read_text())
        self.assertTrue(report["passed"], json.dumps(report["levels"], indent=1)[:4000])
        return report

    def cloud_candles(self, timeframe="1m"):
        return pg_rows(self.dsn, """
            SELECT c.source_id, to_char(c.ts AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD HH24:MI'), c.close
            FROM candles c WHERE c.timeframe = %s ORDER BY c.ts""", (timeframe,))

    def changelog_backlog(self):
        return sqlite_rows(self.sqlite, "SELECT count(*) FROM _changelog")[0][0]


class CdcAndSyncTest(SyncTestBase):
    def test_insert_after_cdc_install_reaches_postgres_and_changelog_is_pruned(self):
        from utils.db_func import store_market_data
        self.assertEqual(sqlite_rows(self.sqlite, "PRAGMA journal_mode")[0][0], "wal")
        store_market_data(candles_df("2026-03-27 09:15", [23000.05, 23010.10]), interval="1m",
                          db_path=str(self.sqlite))
        self.assertEqual(self.changelog_backlog(), 2)

        self.sync_once()

        self.assertEqual(self.cloud_candles(), [(1, "2026-03-27 09:15", Decimal("23000.05")),
                                                (2, "2026-03-27 09:16", Decimal("23010.10"))])
        self.assertEqual(self.changelog_backlog(), 0)  # acknowledged entries are pruned
        self.assertEqual(pg_rows(self.dsn, "SELECT last_seq FROM sync_state WHERE source_table = 'market_data_1m'"),
                         [(2,)])
        self.reconcile()

    def test_revised_candle_is_reflected_in_the_cloud(self):
        from utils.db_func import store_market_data
        store_market_data(candles_df("2026-03-27 09:15", [23000.0, 23010.0]), interval="1m", db_path=str(self.sqlite))
        self.sync_once()
        # The bot re-writes the same minute (its ON CONFLICT(symbol, timestamp) DO UPDATE path):
        # same id, new close. A max(id) watermark would never see this change.
        store_market_data(candles_df("2026-03-27 09:16", [23012.5]), interval="1m", db_path=str(self.sqlite))
        self.assertEqual(sqlite_rows(self.sqlite, "SELECT id, close FROM market_data_1m ORDER BY id"),
                         [(1, 23000.0), (2, 23012.5)])

        self.sync_once()

        self.assertEqual(self.cloud_candles(), [(1, "2026-03-27 09:15", Decimal("23000.00")),
                                                (2, "2026-03-27 09:16", Decimal("23012.50"))])
        self.reconcile()

    def test_delete_and_rebuild_of_hourly_candles_reaches_the_cloud(self):
        from utils.db_func import store_market_data
        from utils.market_data_1h import backfill_market_data_1h
        store_market_data(candles_df("2026-03-27 09:15", [23000.0 + i for i in range(12)], freq="15min"),
                          interval="15m", db_path=str(self.sqlite))
        backfill_market_data_1h(db_path=str(self.sqlite))
        self.sync_once()
        first_ids = [r[0] for r in self.cloud_candles("1h")]
        self.assertEqual(len(first_ids), 3)

        # The bot's backfill DELETEs every 1h row for the symbol and inserts fresh ones (new ids).
        backfill_market_data_1h(db_path=str(self.sqlite))
        self.sync_once()

        after = self.cloud_candles("1h")
        self.assertEqual([r[0] for r in after],
                         [r[0] for r in sqlite_rows(self.sqlite, "SELECT id FROM market_data_1h ORDER BY timestamp")])
        self.assertTrue(set(first_ids).isdisjoint(r[0] for r in after))
        self.reconcile()

    def test_insert_or_replace_vix_and_deleted_signal_propagate(self):
        from utils.db_func import store_signal, store_vix_data_bulk
        from utils.vix_fetcher import store_vix_data
        import pandas as pd
        store_vix_data_bulk(pd.DataFrame({"vix_value": [14.1, 14.2]},
                                         index=pd.DatetimeIndex(["2026-03-27 09:15:00", "2026-03-27 09:16:00"])),
                            "NIFTY50", db_path=str(self.sqlite))
        store_signal("2026-03-27 09:45:00", "NIFTY50", "SELL", "AO crossover below 0", 0.75, db_path=str(self.sqlite))
        store_signal("2026-03-27 10:45:00", "NIFTY50", "BUY", "AO crossover above 0", 0.75, db_path=str(self.sqlite))
        self.sync_once()

        # INSERT OR REPLACE removes the old row without firing a DELETE trigger; its INSERT entry still syncs.
        store_vix_data("2026-03-27 09:16:00", "NIFTY50", 15.5, db_path=str(self.sqlite))
        conn = sqlite3.connect(self.sqlite)
        conn.execute("DELETE FROM signals WHERE id = 1")
        conn.commit()
        conn.close()
        self.sync_once()

        self.assertEqual(pg_rows(self.dsn, "SELECT value FROM vix_observations ORDER BY ts"), [(14.1,), (15.5,)])
        self.assertEqual(pg_rows(self.dsn, "SELECT id, signal FROM signals"), [(2, "BUY")])
        self.reconcile()

    def test_hourly_smas_with_a_composite_key_follow_rebuilds_replaces_and_deletes(self):
        from utils.db_func import store_market_data, store_sma_from_df
        from utils.market_data_1h import backfill_market_data_1h
        store_market_data(candles_df("2026-03-27 09:15", [23000.0 + i for i in range(12)], freq="15min"),
                          interval="15m", db_path=str(self.sqlite))
        backfill_market_data_1h(db_path=str(self.sqlite))  # deletes, then re-stores 1h candles AND their SMAs
        self.sync_once()
        # INSERT OR REPLACE on the composite key (timestamp, symbol): new values for existing hours, plus a new hour.
        store_sma_from_df(candles_df("2026-03-27 11:15", [23500.0, 23510.0], freq="1h"), "NIFTY50", "1h",
                          db_path=str(self.sqlite))
        conn = sqlite3.connect(self.sqlite)
        conn.execute("DELETE FROM market_sma_1h WHERE timestamp = '2026-03-27 09:15:00'")
        conn.commit()
        conn.close()

        self.sync_once()

        source = sqlite_rows(self.sqlite, "SELECT timestamp, sma_5, sma_20 FROM market_sma_1h ORDER BY timestamp")
        self.assertEqual([r[0] for r in source], ["2026-03-27 10:15:00", "2026-03-27 11:15:00", "2026-03-27 12:15:00"])
        self.assertEqual(pg_rows(self.dsn, """
            SELECT to_char(ts AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD HH24:MI:SS'), sma_5, sma_20
            FROM candle_sma ORDER BY ts"""), source)
        self.reconcile()


class ExactlyOnceTest(SyncTestBase):
    def write_minutes(self, n, start="2026-03-27 09:15"):
        from utils.db_func import store_market_data
        store_market_data(candles_df(start, [23000.0 + i for i in range(n)]), interval="1m", db_path=str(self.sqlite))

    def test_many_changes_sync_in_batches(self):
        self.write_minutes(10)

        proc = self.sync_once("--batch-size", "3")

        self.assertEqual(json.loads(proc.stdout)["batches"], 4)
        self.assertEqual(pg_rows(self.dsn, "SELECT first_seq, last_seq, entries FROM sync_batches ORDER BY batch_id"),
                         [(1, 3, 3), (4, 6, 3), (7, 9, 3), (10, 10, 1)])
        self.assertEqual(len(self.cloud_candles()), 10)
        self.reconcile()

    def test_crash_mid_batch_then_rerun_leaves_no_duplicates_or_gaps(self):
        self.write_minutes(10)

        proc = self.sync_once("--batch-size", "4", env={"CLOUDSYNC_FAULT": "mid_batch:2"}, check=False)

        self.assertEqual(proc.returncode, 75, proc.stderr)
        # Batch 1 committed; batch 2 died inside its transaction, so none of it is visible.
        self.assertEqual([r[0] for r in self.cloud_candles()], [1, 2, 3, 4])
        self.assertEqual(pg_rows(self.dsn, "SELECT last_seq FROM sync_state"), [(4,)])
        self.assertEqual(self.changelog_backlog(), 6)

        self.sync_once("--batch-size", "4")

        self.assertEqual([r[0] for r in self.cloud_candles()], list(range(1, 11)))
        self.assertEqual(self.changelog_backlog(), 0)
        self.reconcile()

    def test_crash_after_commit_before_prune_is_harmless(self):
        self.write_minutes(5)

        proc = self.sync_once(env={"CLOUDSYNC_FAULT": "after_commit:1"}, check=False)

        self.assertEqual(proc.returncode, 75, proc.stderr)
        self.assertEqual(len(self.cloud_candles()), 5)
        self.assertEqual(self.changelog_backlog(), 5)  # committed in Postgres, not yet pruned in SQLite

        summary = json.loads(self.sync_once().stdout)

        self.assertEqual(summary["entries"], 0)  # nothing re-applied: sync_state already covers them
        self.assertEqual(self.changelog_backlog(), 0)
        self.assertEqual(pg_rows(self.dsn, "SELECT count(*) FROM sync_batches"), [(1,)])
        self.reconcile()



class OfflineRecoveryTest(SyncTestBase):
    def write_minutes(self, n):
        from utils.db_func import store_market_data
        store_market_data(candles_df("2026-03-27 09:15", [23000.0 + i for i in range(n)]), interval="1m",
                          db_path=str(self.sqlite))

    def test_postgres_unreachable_then_available_catches_up(self):
        self.write_minutes(3)
        offline = dsn_via_port(self.dsn, free_port())  # nothing listens there

        proc = run_cli("sync", "once", "--sqlite", self.sqlite, "--dsn", offline,
                       "--max-retries", "2", "--backoff", "0.1", check=False)

        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr.count("retry "), 2, proc.stderr)  # 0.1 s, then 0.2 s
        self.assertEqual(self.changelog_backlog(), 3)  # nothing acknowledged, nothing lost

        self.sync_once()

        self.assertEqual(len(self.cloud_candles()), 3)
        self.assertEqual(self.changelog_backlog(), 0)
        self.reconcile()

    def test_daemon_backs_off_while_offline_and_resumes_when_the_network_returns(self):
        import subprocess
        import sys
        import time
        from tests.support import PROJECT_ROOT
        port = free_port()
        link = TcpForwarder(port)
        self.addCleanup(link.stop)
        daemon = subprocess.Popen(
            [sys.executable, "-m", "cloudsync", "sync", "daemon", "--sqlite", str(self.sqlite),
             "--dsn", dsn_via_port(self.dsn, port), "--poll", "0.2", "--backoff", "0.2", "--backoff-cap", "1"],
            cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        def stop_daemon():
            daemon.kill()
            return daemon.communicate(timeout=10)[0]

        try:
            self.write_minutes(4)
            time.sleep(4)  # link down: the daemon can only back off
            self.assertEqual(self.cloud_candles(), [])
            link.start()   # network comes back
            deadline = time.time() + 30
            while time.time() < deadline and self.changelog_backlog():
                time.sleep(0.25)
            self.assertEqual(len(self.cloud_candles()), 4)
            self.write_minutes(6)  # keeps up continuously once connected (4 rewrites + 2 new rows)
            deadline = time.time() + 15
            while time.time() < deadline and (self.changelog_backlog() or len(self.cloud_candles()) < 6):
                time.sleep(0.25)
        finally:
            output = stop_daemon()
        self.assertIn("retrying in", output)
        self.assertIn("connected again", output)
        self.assertEqual(len(self.cloud_candles()), 6, output)
        self.reconcile()


class DataQualityThroughSyncTest(SyncTestBase):
    def test_quarantined_candle_is_released_when_the_bot_corrects_it(self):
        from utils.db_func import store_market_data
        bad = candles_df("2026-03-27 09:15", [23000.0, 23001.0])
        bad.iloc[1, bad.columns.get_loc("low")] = 23100.0  # low above high
        store_market_data(bad, interval="1m", db_path=str(self.sqlite))
        self.sync_once()
        self.assertEqual(pg_rows(self.dsn, "SELECT source_pk FROM rejected_rows"), [("2",)])

        store_market_data(candles_df("2026-03-27 09:16", [23001.0]), interval="1m", db_path=str(self.sqlite))
        self.sync_once()

        self.assertEqual(pg_rows(self.dsn, "SELECT count(*) FROM rejected_rows"), [(0,)])
        self.assertEqual([r[0] for r in self.cloud_candles()], [1, 2])
        l1 = self.reconcile()["levels"]["1"]["tables"]["market_data_1m"]
        self.assertEqual((l1["sqlite"], l1["postgres"], l1["rejected"]), (2, 2, 0))

    def write_deltas_with_duplicates(self):
        """Bot option chain + delta builder, then one historical duplicate per row (as older bot versions did)."""
        from tests.test_bulk_load_reconcile import BulkLoadReconcileTest
        helper = BulkLoadReconcileTest("test_delta_snapshots_load_and_reconcile")
        helper.sqlite = self.sqlite
        helper.write_option_chain()
        helper.build_deltas()
        n = sqlite_rows(self.sqlite, "SELECT count(*) FROM delta_cache")[0][0]
        conn = sqlite3.connect(self.sqlite)
        conn.execute("""INSERT INTO delta_cache (timestamp, strike_price, option_type, delta, expiry_date,
                                                 spot_price, symbol, ltp, tradingsymbol)
                        SELECT timestamp, strike_price, option_type, delta + 1.5, expiry_date,
                               spot_price, symbol, ltp, tradingsymbol FROM delta_cache ORDER BY id""")
        conn.commit()
        conn.close()
        return n

    def test_delta_duplicates_via_cdc_and_deleting_the_survivor_promotes_its_sibling(self):
        n = self.write_deltas_with_duplicates()
        self.sync_once("--batch-size", "5")  # duplicates arrive across several batches
        self.assertEqual(pg_rows(self.dsn, "SELECT min(source_id), max(source_id) FROM delta_snapshots"),
                         [(n + 1, 2 * n)])
        self.reconcile()

        # Delete one surviving (highest-id) row at the source: its quarantined sibling must take its place.
        conn = sqlite3.connect(self.sqlite)
        conn.execute("DELETE FROM delta_cache WHERE id = ?", (2 * n,))
        conn.commit()
        conn.close()
        self.sync_once()

        survivors = {r[0] for r in pg_rows(self.dsn, "SELECT source_id FROM delta_snapshots")}
        self.assertNotIn(2 * n, survivors)
        self.assertIn(n, survivors)  # the original of that pair, promoted from rejected_rows
        self.assertEqual(len(survivors), n)
        l1 = self.reconcile()["levels"]["1"]["tables"]["delta_cache"]
        self.assertEqual((l1["sqlite"], l1["postgres"], l1["rejected"]), (2 * n - 1, n, n - 1))

    def test_observed_option_row_corrects_a_contract_derived_from_an_earlier_trade(self):
        # A monthly trade symbol carries no expiry day: it is derived as the last Tuesday (24 Nov 2026).
        conn = sqlite3.connect(self.sqlite)
        conn.execute("""INSERT INTO dashboard_trade_history (strategy_id, symbol, entry_ts, side, qty, entry_price,
                        status, source) VALUES ('nifty-options', 'NIFTY26NOV23000CE', '2026-11-05 10:00:00',
                        'BUY', 50, 120.5, 'OPEN', 'live-sync')""")
        conn.commit()
        self.sync_once()
        self.assertEqual(pg_rows(self.dsn, """SELECT oc.expiry_date::text, oc.expiry_source FROM option_contracts oc
                                              WHERE oc.tradingsymbol = 'NIFTY26NOV23000CE'"""),
                         [("2026-11-24", "derived")])

        # Then the feed reports that contract with its real (holiday-shifted) expiry.
        conn.execute("""INSERT INTO option_data (timestamp, symbol, strike_price, option_type, ltp, iv, expiry_date,
                        spot_price, tradingsymbol, open_interest) VALUES ('2026-11-05 10:01:00', 'NIFTY50', 23000,
                        'CE', 118.0, 0.21, '2026-11-23', 23010.0, 'NIFTY26NOV23000CE', 1000)""")
        conn.commit()
        conn.close()
        self.sync_once()

        self.assertEqual(
            pg_rows(self.dsn, """SELECT oc.expiry_date::text, oc.expiry_source, count(DISTINCT t.id),
                                        count(DISTINCT s.source_id)
                                 FROM option_contracts oc
                                 LEFT JOIN dashboard_trade_history t ON t.contract_id = oc.id
                                 LEFT JOIN option_snapshots s ON s.contract_id = oc.id
                                 WHERE oc.tradingsymbol = 'NIFTY26NOV23000CE' GROUP BY 1, 2"""),
            [("2026-11-23", "observed", 1, 1)])
        self.reconcile()


class SchemaDriftTest(SyncTestBase):
    def test_added_column_pauses_only_that_table_until_a_migration_and_resume(self):
        from utils.db_func import store_market_data, store_signal
        conn = sqlite3.connect(self.sqlite)
        conn.execute("ALTER TABLE signals ADD COLUMN strategy_tag TEXT")  # a future bot schema change
        conn.commit()
        conn.close()
        store_signal("2026-03-27 09:45:00", "NIFTY50", "SELL", "AO crossover below 0", 0.75, db_path=str(self.sqlite))
        store_market_data(candles_df("2026-03-27 09:15", [23000.0]), interval="1m", db_path=str(self.sqlite))

        proc = self.sync_once()

        self.assertEqual(json.loads(proc.stdout)["paused_tables"], ["signals"])
        self.assertIn("SCHEMA DRIFT: signals", proc.stderr)
        self.assertEqual(len(self.cloud_candles()), 1)               # other tables keep syncing
        self.assertEqual(pg_rows(self.dsn, "SELECT count(*) FROM signals"), [(0,)])
        self.assertEqual(sqlite_rows(self.sqlite, "SELECT table_name FROM _changelog"), [("signals",)])  # kept

        refused = run_cli("drift-resume", "--sqlite", self.sqlite, "--dsn", self.dsn, "--table", "signals",
                          check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("apply a migration", refused.stderr)

        drift_dir = self.tmp / "drift_migrations"
        drift_dir.mkdir()
        (drift_dir / "9001_signals_strategy_tag.sql").write_text(
            "ALTER TABLE signals ADD COLUMN strategy_tag text;\n", encoding="utf-8")
        run_cli("migrate", "--dsn", self.dsn, "--extra-dir", drift_dir)
        run_cli("drift-resume", "--sqlite", self.sqlite, "--dsn", self.dsn, "--table", "signals")
        self.sync_once()

        self.assertEqual(pg_rows(self.dsn, "SELECT id, signal FROM signals"), [(1, "SELL")])
        self.assertEqual(pg_rows(self.dsn, "SELECT status FROM schema_fingerprints WHERE source_table = 'signals'"),
                         [("active",)])
        self.assertEqual(pg_rows(self.dsn, "SELECT max(version) FROM schema_version"), [(9001,)])
        self.reconcile()


if __name__ == "__main__":
    unittest.main()
