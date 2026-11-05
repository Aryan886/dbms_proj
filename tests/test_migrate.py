import unittest

from tests.support import make_pg_database, pg_rows, run_cli


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.dsn = make_pg_database(self)

    def test_migrate_records_versions_and_is_idempotent(self):
        first = run_cli("migrate", "--dsn", self.dsn)
        versions = pg_rows(self.dsn, "SELECT version FROM schema_version ORDER BY version")
        self.assertGreaterEqual(len(versions), 1)
        self.assertEqual(versions[0][0], 1)

        second = run_cli("migrate", "--dsn", self.dsn)
        self.assertEqual(pg_rows(self.dsn, "SELECT version FROM schema_version ORDER BY version"), versions)
        self.assertIn("applied 0", second.stdout)
        self.assertNotIn("applied 0", first.stdout)

    def test_master_instruments_are_seeded(self):
        run_cli("migrate", "--dsn", self.dsn)
        self.assertEqual(
            pg_rows(self.dsn, "SELECT symbol, kind FROM instruments ORDER BY symbol"),
            [("INDIA VIX", "volatility_index"), ("INFY", "equity"), ("NIFTY50", "index")],
        )


if __name__ == "__main__":
    unittest.main()
