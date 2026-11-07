-- 0007: stored hourly SMAs (market_sma_1h), the 11th in-scope source table.
--
-- The spec listed the SMA tables as never read. Day 3 found that the
-- backtester merges market_sma_1h into its 1h candles and the strategy reads
-- sma_20/50/200 from it (Main Category A, sub-categories l/n/o). The stored
-- values cannot be recomputed with a window function (they restart after
-- data gaps), so, like candle_indicators, they are kept as stored values for
-- exact parity. The SQL-computed SMA view (0008) shows the window functions
-- and the drift between the two.
--
-- No foreign key to candles: in SQLite the bot writes and deletes SMA rows
-- independently of the candles (its 1h rebuild clears them separately), so a
-- FK would make the sync depend on the bot's write order. The data-quality
-- view reports SMA rows without a candle instead.
CREATE TABLE candle_sma (
    instrument_id  smallint NOT NULL REFERENCES instruments(id),
    timeframe      text NOT NULL CHECK (timeframe IN ('1m', '5m', '15m', '1h')),
    ts             timestamptz NOT NULL,
    sma_5          double precision,
    sma_20         double precision,
    sma_50         double precision,
    sma_200        double precision,
    sma_5_high     double precision,
    sma_5_low      double precision,
    PRIMARY KEY (instrument_id, timeframe, ts)
);

CREATE VIEW compat.market_sma_1h AS
SELECT (s.ts AT TIME ZONE 'Asia/Kolkata') AS "timestamp",
       i.symbol                           AS symbol,
       s.sma_5, s.sma_20, s.sma_50, s.sma_200, s.sma_5_high, s.sma_5_low
FROM candle_sma s
JOIN instruments i ON i.id = s.instrument_id
WHERE s.timeframe = '1h';
