-- 0001: normalized (3NF) base schema for the AlgoTrade cloud copy.
-- Typing rule ("split typing"): exchange-quoted prices that round-trip exactly
-- at 2 dp are NUMERIC(12,2); computed values (option ltp/iv/delta, indicators,
-- VIX) stay double precision so the bot's floats are preserved bit-for-bit.
-- All source timestamps are naive Asia/Kolkata wall-clock text -> timestamptz.

-- ---------- master data ----------
CREATE TABLE instruments (
    id      smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol  text NOT NULL UNIQUE,
    kind    text NOT NULL CHECK (kind IN ('index', 'equity', 'volatility_index'))
);
INSERT INTO instruments (symbol, kind) VALUES
    ('NIFTY50', 'index'), ('INFY', 'equity'), ('INDIA VIX', 'volatility_index');

CREATE TABLE option_contracts (
    id             integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_id  smallint NOT NULL REFERENCES instruments(id),
    expiry_date    date NOT NULL,
    strike         integer NOT NULL CHECK (strike > 0),
    option_type    char(2) NOT NULL CHECK (option_type IN ('CE', 'PE')),
    tradingsymbol  text UNIQUE,
    -- 'observed': expiry read from option_data/delta_cache rows.
    -- 'derived' : parsed from a tradingsymbol only (monthly = last Tuesday of month).
    expiry_source  text NOT NULL DEFAULT 'observed' CHECK (expiry_source IN ('observed', 'derived')),
    CONSTRAINT option_contracts_natural_key UNIQUE (instrument_id, expiry_date, strike, option_type)
);

-- ---------- market facts ----------
-- One table replaces market_data_1m/5m/15m/1h. source_id is the SQLite
-- AUTOINCREMENT id (kept for compatibility views and for mapping CDC deletes).
CREATE TABLE candles (
    instrument_id  smallint NOT NULL REFERENCES instruments(id),
    timeframe      text NOT NULL CHECK (timeframe IN ('1m', '5m', '15m', '1h')),
    ts             timestamptz NOT NULL,
    source_id      bigint NOT NULL,
    open           numeric(12,2) NOT NULL,
    high           numeric(12,2) NOT NULL,
    low            numeric(12,2) NOT NULL,
    close          numeric(12,2) NOT NULL,
    volume         bigint CHECK (volume >= 0),
    PRIMARY KEY (instrument_id, timeframe, ts),
    CONSTRAINT candles_source_id_key UNIQUE (timeframe, source_id),
    CONSTRAINT candles_ohlc_low_le_high    CHECK (low <= high),
    CONSTRAINT candles_ohlc_open_in_range  CHECK (open  BETWEEN low AND high),
    CONSTRAINT candles_ohlc_close_in_range CHECK (close BETWEEN low AND high),
    CONSTRAINT candles_positive_prices     CHECK (low > 0)
);

-- Values the bot itself wrote next to each candle. Kept stored (not only as
-- views) because the strategy reads stored donchian_mid and SL/SH come from a
-- path-dependent backfill. vix_value is a documented denormalization.
CREATE TABLE candle_indicators (
    instrument_id   smallint NOT NULL,
    timeframe       text NOT NULL,
    ts              timestamptz NOT NULL,
    ao_value        double precision,
    donchian_upper  double precision,
    donchian_lower  double precision,
    donchian_mid    double precision,
    sl              double precision,
    sh              double precision,
    vix_value       double precision,
    PRIMARY KEY (instrument_id, timeframe, ts),
    FOREIGN KEY (instrument_id, timeframe, ts)
        REFERENCES candles (instrument_id, timeframe, ts) ON DELETE CASCADE
);

CREATE TABLE vix_observations (
    ts              timestamptz PRIMARY KEY,
    instrument_id   smallint REFERENCES instruments(id),  -- underlying it was observed for (source "symbol")
    value           double precision NOT NULL CHECK (value >= 0),
    ao_value        double precision,
    donchian_upper  double precision,
    donchian_lower  double precision,
    donchian_mid    double precision
);

-- From option_data.
CREATE TABLE option_snapshots (
    contract_id    integer NOT NULL REFERENCES option_contracts(id),
    ts             timestamptz NOT NULL,
    source_id      bigint NOT NULL UNIQUE,
    ltp            double precision CHECK (ltp >= 0),
    iv             double precision,
    spot_price     numeric(12,2) CHECK (spot_price > 0),
    open_interest  bigint CHECK (open_interest >= 0),
    PRIMARY KEY (contract_id, ts)
);

-- From delta_cache. Duplicates on (contract, ts) are resolved by keeping the
-- highest source id; the rest are quarantined in rejected_rows.
CREATE TABLE delta_snapshots (
    contract_id  integer NOT NULL REFERENCES option_contracts(id),
    ts           timestamptz NOT NULL,
    source_id    bigint NOT NULL UNIQUE,
    delta        double precision CHECK (delta BETWEEN -100 AND 100),
    spot_price   numeric(12,2) CHECK (spot_price > 0),
    ltp          double precision CHECK (ltp >= 0),
    PRIMARY KEY (contract_id, ts)
);

CREATE TABLE signals (
    id                bigint PRIMARY KEY,           -- SQLite id
    instrument_id     smallint NOT NULL REFERENCES instruments(id),
    ts                timestamptz NOT NULL,
    signal            text CHECK (signal IN ('BUY', 'SELL')),
    reason            text,
    confidence_score  double precision CHECK (confidence_score BETWEEN 0 AND 1)
);

-- ---------- dashboard / trading records ----------
CREATE TABLE dashboard_strategy_state (
    strategy_id      text PRIMARY KEY,
    display_name     text NOT NULL,
    status           text NOT NULL,
    mode             text NOT NULL,
    last_started_at  timestamptz,
    last_stopped_at  timestamptz,
    updated_at       timestamptz NOT NULL
);

CREATE TABLE dashboard_trade_history (
    id              bigint PRIMARY KEY,             -- SQLite id
    strategy_id     text NOT NULL REFERENCES dashboard_strategy_state(strategy_id),
    instrument_id   smallint NOT NULL REFERENCES instruments(id),
    contract_id     integer REFERENCES option_contracts(id),
    entry_ts        timestamptz NOT NULL,
    exit_ts         timestamptz,
    side            text NOT NULL CHECK (side IN ('BUY', 'SELL')),
    qty             integer NOT NULL CHECK (qty > 0),
    entry_price     numeric(12,2) NOT NULL,
    exit_price      numeric(12,2),
    realized_pnl    numeric(14,2),
    status          text NOT NULL CHECK (status IN ('OPEN', 'CLOSED')),
    source          text NOT NULL,
    position_type   text,
    section         text,
    subcat          text,
    exit_reason     text,
    sl_initial      numeric(12,2),
    sl_final        numeric(12,2),
    sl_adjustments  integer NOT NULL DEFAULT 0 CHECK (sl_adjustments >= 0),
    CHECK (exit_ts IS NULL OR exit_ts >= entry_ts)
);

-- ---------- pipeline bookkeeping ----------
CREATE TABLE rejected_rows (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_table         text NOT NULL,
    source_pk            text,
    raw_row              jsonb NOT NULL,
    violated_constraint  text NOT NULL,
    detail               text,
    rejected_at          timestamptz NOT NULL DEFAULT now()
);
