"""Smoke test for the WAL benchmark: it measures, it does not pass/fail on numbers (see SPEC)."""
import json
import unittest

from tests.support import make_bot_db, make_tmpdir, run_cli, sqlite_rows


class WalBenchmarkTest(unittest.TestCase):
    def test_benchmark_reports_both_journal_modes_and_leaves_the_source_untouched(self):
        tmp = make_tmpdir(self)
        db = make_bot_db(tmp / "trading_bot.db")
        out = tmp / "bench"

        run_cli("bench-wal", "--sqlite", db, "--out", out, "--seconds", "1", "--table", "dashboard_trade_history")

        report = json.loads((out / "wal_benchmark.json").read_text())
        self.assertEqual([m["journal_mode"] for m in report["modes"]], ["delete", "wal"])
        for m in report["modes"]:
            self.assertGreater(m["writes_ok"] + m["write_lock_errors"], 0)
            self.assertGreater(m["reads_ok"] + m["read_lock_errors"], 0)
        self.assertTrue((out / "wal_benchmark.md").exists())
        self.assertEqual(sqlite_rows(db, "PRAGMA journal_mode")[0][0], "delete")
        self.assertEqual(sqlite_rows(db, "SELECT count(*) FROM sqlite_master WHERE name = '_bench_writes'"), [(0,)])


if __name__ == "__main__":
    unittest.main()
