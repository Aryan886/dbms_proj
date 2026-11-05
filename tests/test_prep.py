import hashlib
import json
import sqlite3
import unittest

import pandas as pd

from tests.support import make_bot_db, make_tmpdir, run_cli, sqlite_rows


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PrepTest(unittest.TestCase):
    def setUp(self):
        from utils.db_func import store_vix_data_bulk
        self.tmp = make_tmpdir(self)
        self.source = make_bot_db(self.tmp / "source" / "trading_bot.db")
        idx = pd.date_range("2026-03-27 09:15", periods=5000, freq="s")
        store_vix_data_bulk(pd.DataFrame({"vix_value": range(5000)}, index=idx), "NIFTY50", db_path=str(self.source))
        # The bot prunes old rows; deletes leave free pages behind.
        conn = sqlite3.connect(self.source)
        conn.execute("DELETE FROM vix_data WHERE vix_value < 4900")
        conn.commit()
        conn.close()
        self.workdir = self.tmp / "work"

    def test_prep_makes_vacuumed_working_copy_and_leaves_source_untouched(self):
        before_hash = file_hash(self.source)

        run_cli("prep", "--source", self.source, "--workdir", self.workdir)

        self.assertEqual(file_hash(self.source), before_hash)
        working = self.workdir / "trading_bot.db"
        self.assertEqual(sqlite_rows(working, "SELECT count(*) FROM vix_data"), [(100,)])

        stats = json.loads((self.workdir / "artifacts" / "prep_stats.json").read_text())
        before, after = stats["before_vacuum"], stats["after_vacuum"]
        self.assertGreater(before["freelist_count"], 0)
        self.assertEqual(after["freelist_count"], 0)
        self.assertLess(after["file_size_bytes"], before["file_size_bytes"])
        self.assertEqual(after["file_size_bytes"], working.stat().st_size)
        self.assertEqual(after["page_count"] * after["page_size"], after["file_size_bytes"])


if __name__ == "__main__":
    unittest.main()
