"""End-to-end: indicators computed in SQL with window functions, and their drift
against the values the bot stored.

Expected values are worked by hand from a linear series, close_i = 100 + i,
high = close + 5, low = close - 5 (so the median price (high + low) / 2 = close):
  * SMA_n (the bot's expanding window, min_periods=1): mean of the last min(n, i+1) closes
        i < n-1 : 100 + i/2          i >= n-1 : close_i - (n-1)/2
  * AO = SMA_5(median) - SMA_34(median), full windows only: (close_i - 2) - (close_i - 16.5)
        = 14.5 from i = 33, NULL before
  * Donchian(20), full windows only, from i = 19:
        upper = close_i + 5, lower = close_{i-19} - 5 = close_i - 24, mid = close_i - 9.5
"""
import unittest

import pandas as pd

from tests.support import make_bot_db, make_pg_database, make_tmpdir, pg_rows, run_cli


def linear_candles(n, start="2026-03-02 09:15", freq="1h"):
    closes = [100.0 + i for i in range(n)]
    idx = pd.date_range(start, periods=n, freq=freq)
    return pd.DataFrame({"open": closes, "high": [c + 5 for c in closes], "low": [c - 5 for c in closes],
                         "close": closes}, index=idx)


class IndicatorViewTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmpdir(self)
        self.sqlite = make_bot_db(self.tmp / "trading_bot.db")
        self.dsn = make_pg_database(self)
        run_cli("migrate", "--dsn", self.dsn)

    def load(self):
        run_cli("bulk-load", "--sqlite", self.sqlite, "--dsn", self.dsn)


class ComputedIndicatorViewTest(IndicatorViewTestBase):
    def test_window_function_indicators_match_the_hand_worked_series(self):
        from utils.db_func import store_market_data
        store_market_data(linear_candles(40), interval="1h", db_path=str(self.sqlite))
        self.load()

        rows = {r[0]: r[1:] for r in pg_rows(self.dsn, """
            SELECT to_char(ts AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD HH24:MI'), sma_5, sma_20, sma_200,
                   ao_value, donchian_upper, donchian_lower, donchian_mid
            FROM candle_indicators_computed
            WHERE timeframe = '1h' AND symbol = 'NIFTY50' ORDER BY ts""")}
        self.assertEqual(len(rows), 40)
        at = list(rows.values())
        #               sma_5  sma_20  sma_200  ao    d_upper d_lower d_mid
        self.assertEqual(at[0], (100.0, 100.0, 100.0, None, None, None, None))
        self.assertEqual(at[18], (116.0, 109.0, 109.0, None, None, None, None))
        self.assertEqual(at[19], (117.0, 109.5, 109.5, None, 124.0, 95.0, 109.5))
        self.assertEqual(at[32], (130.0, 122.5, 116.0, None, 137.0, 108.0, 122.5))
        self.assertEqual(at[33], (131.0, 123.5, 116.5, 14.5, 138.0, 109.0, 123.5))
        self.assertEqual(at[39], (137.0, 129.5, 119.5, 14.5, 144.0, 115.0, 129.5))


class IndicatorDriftViewTest(IndicatorViewTestBase):
    def test_drift_view_flags_stored_values_that_restarted_after_a_gap(self):
        """The bot computes indicators per chunk of data it holds, so they restart after a gap
        (as in the real market_sma_1h). Chunk A = rows 0-24, chunk B = rows 25-39.
        Worked drift counts for the 40 hourly rows:
          ao_value       7   stored NULL in both chunks (< 34 rows each), computed 14.5 for i = 33..39
          donchian_mid  15   chunk B (15 rows < 20) stored NULL, computed from i = 19 on
          sma_20        15   chunk B restarts: i = 25 stores 125.0, the full series gives 115.5
          sma_5          4   chunk B's first 4 rows (i = 25..28) are a partial window
          sma_200       15   every chunk-B row averages from i = 25 instead of i = 0"""
        from utils.db_func import store_market_data, store_sma_from_df
        from utils.market_data_1h import add_true_hourly_indicators
        series = linear_candles(40)
        for chunk in (series.iloc[:25], series.iloc[25:]):
            store_market_data(add_true_hourly_indicators(chunk), interval="1h", db_path=str(self.sqlite))
            store_sma_from_df(chunk, "NIFTY50", "1h", db_path=str(self.sqlite))
        self.load()

        summary = {r[0]: r[1:] for r in pg_rows(self.dsn, """
            SELECT indicator, rows_compared, rows_drifted FROM dq_indicator_drift_summary
            WHERE timeframe = '1h' AND symbol = 'NIFTY50'""")}
        self.assertEqual(summary["ao_value"], (40, 7))
        self.assertEqual(summary["donchian_upper"], (40, 15))
        self.assertEqual(summary["donchian_mid"], (40, 15))
        self.assertEqual(summary["sma_20"], (40, 15))
        self.assertEqual(summary["sma_5"], (40, 4))
        self.assertEqual(summary["sma_200"], (40, 15))
        self.assertEqual(pg_rows(self.dsn, """
            SELECT to_char(ts AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD HH24:MI'), stored, computed, abs_diff
            FROM dq_indicator_drift WHERE timeframe = '1h' AND indicator = 'sma_20' ORDER BY ts LIMIT 1"""),
                         [("2026-03-03 10:15", 125.0, 115.5, 9.5)])


if __name__ == "__main__":
    unittest.main()
