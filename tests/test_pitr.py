"""End-to-end: the database side of the point-in-time-recovery demo (spec story 45).

`pitr snapshot` fingerprints one IST trading day, `pitr delete-day` deletes it on
purpose and records the server clock around the delete, and `pitr verify` checks a
database (on RDS: the instance restored to a moment before the delete) against the
fingerprint. The restore itself happens in the RDS console; here a TEMPLATE copy
taken before the delete stands in for the restored instance.
"""
import json
import unittest

import psycopg
from psycopg import sql

from tests.support import make_bot_db, make_pg_database, make_tmpdir, pg_rows, run_cli
from tests.test_bulk_load_reconcile import candles_df


def clone_database(testcase, dsn: str) -> str:
    """CREATE DATABASE ... TEMPLATE: a byte-for-byte copy, like a restored instance."""
    src = psycopg.conninfo.conninfo_to_dict(dsn)["dbname"]
    dst = f"{src}_restored"
    admin = psycopg.conninfo.make_conninfo(dsn, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(dst), sql.Identifier(src)))

    def drop():
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(dst)))
    testcase.addCleanup(drop)
    return psycopg.conninfo.make_conninfo(dsn, dbname=dst)


class PitrTest(unittest.TestCase):
    def setUp(self):
        from utils.db_func import store_market_data
        self.tmp = make_tmpdir(self)
        self.sqlite = make_bot_db(self.tmp / "trading_bot.db")
        # Two trading days of 1m candles: one gets deleted, the other must survive.
        store_market_data(candles_df("2026-03-26 09:15", [22900.0 + i for i in range(4)]),
                          interval="1m", db_path=str(self.sqlite))
        store_market_data(candles_df("2026-03-27 09:15", [23000.0 + i for i in range(6)]),
                          interval="1m", db_path=str(self.sqlite))
        self.dsn = make_pg_database(self)
        run_cli("migrate", "--dsn", self.dsn)
        run_cli("bulk-load", "--sqlite", self.sqlite, "--dsn", self.dsn)

    def candles_on(self, dsn, day):
        return pg_rows(dsn, "SELECT count(*) FROM candles WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date = %s",
                       (day,))[0][0]

    def test_a_deleted_day_is_reported_missing_and_a_pre_delete_copy_verifies(self):
        snap = self.tmp / "snapshot.json"
        run_cli("pitr", "snapshot", "--dsn", self.dsn, "--day", "2026-03-27", "--out", snap)
        fingerprint = json.loads(snap.read_text())
        self.assertEqual(fingerprint["tables"]["candles"]["rows"], 6)
        self.assertEqual(fingerprint["tables"]["candle_indicators"]["rows"], 6)

        restored = clone_database(self, self.dsn)  # stands in for the restore to a time before the delete

        deleted = self.tmp / "delete.json"
        run_cli("pitr", "delete-day", "--dsn", self.dsn, "--day", "2026-03-27", "--out", deleted,
                env={"PG_DSN": "", "DOCKER_PG_DSN": ""})
        record = json.loads(deleted.read_text())
        self.assertEqual(record["deleted"]["candles"], 6)
        # The restore target must lie between the snapshot and the start of the delete.
        self.assertLess(fingerprint["server_time"], record["started_at"])
        self.assertLess(record["started_at"], record["committed_at"])
        self.assertEqual(self.candles_on(self.dsn, "2026-03-27"), 0)
        self.assertEqual(self.candles_on(self.dsn, "2026-03-26"), 4)  # only that day was deleted

        damaged = run_cli("pitr", "verify", "--dsn", self.dsn, "--snapshot", snap, check=False)
        self.assertEqual(damaged.returncode, 1, damaged.stdout)
        self.assertIn("FAIL", damaged.stdout)

        ok = run_cli("pitr", "verify", "--dsn", restored, "--snapshot", snap, check=False)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("PASS", ok.stdout)

    def test_delete_day_refuses_the_main_cloud_database(self):
        proc = run_cli("pitr", "delete-day", "--dsn", self.dsn, "--day", "2026-03-27",
                       "--out", self.tmp / "delete.json", env={"PG_DSN": self.dsn}, check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("REFUSED", proc.stdout + proc.stderr)
        self.assertEqual(self.candles_on(self.dsn, "2026-03-27"), 6)


if __name__ == "__main__":
    unittest.main()
