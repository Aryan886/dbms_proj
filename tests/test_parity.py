"""End-to-end: level-3 reconciliation (spec story 34).

`cloudsync reconcile --levels 3` exports the Postgres compatibility views to a
fresh SQLite file, runs the bot's UNCHANGED backtester on the source and on
the export, and diffs the trade lists.

The data is a slice of real days cut from the main working copy (opened
read-only; decision D36), because hand-built candles would almost certainly
make the strategy trade zero times, and two empty trade lists prove nothing.
"""
import json
import sqlite3
import unittest
from pathlib import Path

from tests.support import PROJECT_ROOT, make_pg_database, make_tmpdir, pg_rows, run_cli

WORKING_COPY = PROJECT_ROOT / "data" / "trading_bot.db"

# A window in which the backtester is known to trade on the real data (found with
# a full-range run on a throwaway copy, recorded in docs/logbook/day-03.md).
TRADE_DAY = "2026-03-05"
WARMUP_FROM = "2026-03-02"

IN_SCOPE = ["market_data_1m", "market_data_5m", "market_data_15m", "market_data_1h", "market_sma_1h",
            "vix_data", "signals", "option_data", "delta_cache", "dashboard_strategy_state",
            "dashboard_trade_history"]


def slice_working_copy(dest: Path, start: str, end: str) -> Path:
    """Copy the in-scope tables' DDL, and their rows between start and end, out of the working copy."""
    src_uri = f"file:{WORKING_COPY.resolve().as_posix()}?mode=ro"
    src = sqlite3.connect(src_uri, uri=True)
    out = sqlite3.connect(f"file:{Path(dest).resolve().as_posix()}", uri=True)  # uri=True: ATTACH takes a URI
    try:
        out.execute("ATTACH DATABASE ? AS src", (src_uri,))
        for table in IN_SCOPE:
            for (ddl,) in src.execute("SELECT sql FROM sqlite_master WHERE tbl_name = ? AND type IN ('table', 'index') "
                                      "AND sql IS NOT NULL ORDER BY type = 'index'", (table,)):
                out.execute(ddl)
            if table.startswith("dashboard_"):
                out.execute(f"INSERT INTO main.{table} SELECT * FROM src.{table}")
            else:
                out.execute(f"INSERT INTO main.{table} SELECT * FROM src.{table} "
                            "WHERE timestamp >= ? AND timestamp <= ?", (f"{start} 00:00:00", f"{end} 23:59:59"))
        out.commit()
    finally:
        out.close()
        src.close()
    return dest


@unittest.skipUnless(WORKING_COPY.exists(), "needs the main working copy (cloudsync prep)")
class LevelThreeParityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmpdir(self)
        self.sqlite = slice_working_copy(self.tmp / "slice.db", WARMUP_FROM, TRADE_DAY)
        self.dsn = make_pg_database(self)
        self.report_dir = self.tmp / "report"
        run_cli("migrate", "--dsn", self.dsn)
        run_cli("bulk-load", "--sqlite", self.sqlite, "--dsn", self.dsn)

    def reconcile_level3(self):
        proc = run_cli("reconcile", "--sqlite", self.sqlite, "--dsn", self.dsn, "--levels", "3",
                       "--start", TRADE_DAY, "--end", TRADE_DAY, "--out", self.report_dir, check=False)
        report = json.loads((self.report_dir / "reconciliation.json").read_text())
        return proc, report["levels"]["3"]

    def test_backtest_on_the_cloud_export_makes_the_same_trades(self):
        proc, l3 = self.reconcile_level3()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(l3["passed"], json.dumps(l3["trade_diff"], indent=1)[:3000])
        self.assertGreaterEqual(l3["source"]["num_trades"], 1, "the window must trade, or parity proves nothing")
        self.assertEqual(l3["cloud"], l3["source"])
        self.assertTrue(all(t["identical"] for t in l3["fidelity"].values()), l3["fidelity"])

    def test_a_cloud_copy_missing_option_deltas_fails_and_names_the_lost_trades(self):
        deleted = pg_rows(self.dsn, "DELETE FROM delta_snapshots WHERE ts >= %s::date RETURNING 1", (TRADE_DAY,))
        self.assertGreater(len(deleted), 0)

        proc, l3 = self.reconcile_level3()

        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(l3["passed"])
        self.assertGreater(len(l3["trade_diff"]["only_in_source"]) + len(l3["trade_diff"]["changed"]), 0)
        self.assertFalse(l3["fidelity"]["delta_cache"]["identical"])
        self.assertTrue((self.report_dir / "reconciliation.md").read_text(encoding="utf-8").count("Level 3") >= 1)


if __name__ == "__main__":
    unittest.main()
