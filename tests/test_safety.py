"""Safety rails: the bot's real database is read-only to cloudsync, and experiments run in sandboxes.

The 'real database' here is a stand-in temp file passed as SOURCE_DB / BOT_REPO, so a broken
guard can never touch the actual bot database while testing the guard.
"""
import hashlib
import json
import unittest

from tests.support import make_bot_db, make_pg_database, make_tmpdir, pg_rows, run_cli, sqlite_rows
from tests.test_bulk_load_reconcile import candles_df


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RealDatabaseGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmpdir(self)
        self.bot_repo = self.tmp / "AlgoTrade"
        self.real_db = make_bot_db(self.bot_repo / "db" / "trading_bot.db")
        self.env = {"SOURCE_DB": str(self.real_db), "BOT_REPO": str(self.bot_repo)}
        self.dsn = make_pg_database(self)
        run_cli("migrate", "--dsn", self.dsn)
        self.before = file_hash(self.real_db)

    def assert_refused(self, *args):
        proc = run_cli(*args, env=self.env, check=False)
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("REFUSED", proc.stderr)
        return proc

    def assert_untouched(self):
        self.assertEqual(file_hash(self.real_db), self.before)
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse((self.real_db.parent / (self.real_db.name + suffix)).exists(), suffix)

    def test_commands_that_write_sqlite_refuse_the_real_database(self):
        self.assert_refused("cdc-install", "--sqlite", self.real_db, "--dsn", self.dsn)
        self.assert_refused("sync", "once", "--sqlite", self.real_db, "--dsn", self.dsn)
        self.assert_refused("drift-resume", "--sqlite", self.real_db, "--dsn", self.dsn, "--table", "signals")
        # Anything inside the bot repository is protected too, not just the one file.
        self.assert_refused("prep", "--source", self.real_db, "--workdir", self.bot_repo / "db")
        self.assert_refused("bench-wal", "--sqlite", self.real_db, "--out", self.bot_repo / "bench")
        self.assert_untouched()

    def test_read_only_commands_still_work_on_the_real_database(self):
        work = self.tmp / "work"
        run_cli("prep", "--source", self.real_db, "--workdir", work, env=self.env)
        run_cli("bulk-load", "--sqlite", self.real_db, "--dsn", self.dsn, env=self.env)
        proc = run_cli("reconcile", "--sqlite", self.real_db, "--dsn", self.dsn, "--levels", "1,2",
                       "--out", self.tmp / "report", env=self.env)
        self.assertIn("PASSED", proc.stdout)
        self.assert_untouched()


class SandboxTest(unittest.TestCase):
    """Experiments get a throwaway SQLite copy + a throwaway Postgres clone; the main pair is untouched."""

    def setUp(self):
        self.tmp = make_tmpdir(self)
        self.main_sqlite = make_bot_db(self.tmp / "data" / "trading_bot.db")
        self.main_dsn = make_pg_database(self)
        run_cli("migrate", "--dsn", self.main_dsn)
        run_cli("cdc-install", "--sqlite", self.main_sqlite, "--dsn", self.main_dsn)
        run_cli("bulk-load", "--sqlite", self.main_sqlite, "--dsn", self.main_dsn)

    def test_sandbox_experiment_leaves_the_main_working_copy_and_cloud_untouched(self):
        from utils.db_func import store_market_data
        main_hash = file_hash(self.main_sqlite)
        main_candles = pg_rows(self.main_dsn, "SELECT count(*) FROM candles")

        proc = run_cli("sandbox", "create", "exp1", "--from-sqlite", self.main_sqlite, "--from-dsn", self.main_dsn,
                       "--dir", self.tmp / "sandboxes")
        box = json.loads(proc.stdout)
        self.addCleanup(run_cli, "sandbox", "drop", "exp1", "--from-dsn", self.main_dsn,
                        "--dir", self.tmp / "sandboxes", check=False)

        # The experiment: bot writes + sync, all against the sandbox pair.
        store_market_data(candles_df("2026-03-27 09:15", [23000.0, 23001.0]), interval="1m", db_path=box["sqlite"])
        run_cli("sync", "once", "--sqlite", box["sqlite"], "--dsn", box["dsn"])

        self.assertEqual(pg_rows(box["dsn"], "SELECT count(*) FROM candles"), [(2,)])
        self.assertEqual(sqlite_rows(box["sqlite"], "SELECT count(*) FROM _changelog"), [(0,)])
        self.assertEqual(file_hash(self.main_sqlite), main_hash)
        self.assertEqual(pg_rows(self.main_dsn, "SELECT count(*) FROM candles"), main_candles)

        run_cli("sandbox", "drop", "exp1", "--from-dsn", self.main_dsn, "--dir", self.tmp / "sandboxes")
        self.assertFalse((self.tmp / "sandboxes" / "exp1").exists())


if __name__ == "__main__":
    unittest.main()
