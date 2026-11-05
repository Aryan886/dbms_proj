"""How each in-scope SQLite source table maps onto the normalized Postgres schema.

Every SourceTable knows:
  * how to read its rows from SQLite (`select_sql`, ordered by source pk),
  * the idempotent upsert that writes one source row into the base tables,
  * how to count what it produced in Postgres (level-1 reconciliation).

The same upserts are used by the one-time bulk load and (day 2) by the sync
engine, so both paths share one definition of "a source row in the cloud".
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceTable:
    name: str
    pk: str
    select_sql: str
    upsert_sql: str
    pg_count_sql: str
    # Level-2 checksum: the source timestamp column and the numeric measure
    # summed per day, plus the equivalent Postgres query returning rows of
    # (day 'YYYY-MM-DD', count, sum float8, min ts text, max ts text).
    ts_col: str
    measure_col: str
    pg_daily_sql: str


def _daily(from_where: str, ts: str, measure: str) -> str:
    fmt = "'YYYY-MM-DD HH24:MI:SS'"
    return f"""
        SELECT to_char({ts}, 'YYYY-MM-DD') AS day, count(*), sum({measure})::float8,
               to_char(min({ts}), {fmt}), to_char(max({ts}), {fmt})
        FROM {from_where} GROUP BY 1 ORDER BY 1"""


def _market_data(timeframe: str) -> SourceTable:
    name = f"market_data_{timeframe}"
    return SourceTable(
        name=name,
        pk="id",
        select_sql=f"""
            SELECT id, timestamp, symbol, open, high, low, close,
                   ao_value, donchian_upper, donchian_lower, donchian_mid, SL, SH, vix_value
            FROM {name} ORDER BY id""",
        upsert_sql=f"""
            WITH c AS (
                INSERT INTO candles (instrument_id, timeframe, ts, source_id, open, high, low, close)
                VALUES ((SELECT id FROM instruments WHERE symbol = %(symbol)s), '{timeframe}',
                        %(timestamp)s::timestamptz, %(id)s, %(open)s, %(high)s, %(low)s, %(close)s)
                ON CONFLICT (instrument_id, timeframe, ts) DO UPDATE SET
                    source_id = EXCLUDED.source_id, open = EXCLUDED.open, high = EXCLUDED.high,
                    low = EXCLUDED.low, close = EXCLUDED.close
                RETURNING instrument_id, timeframe, ts
            )
            INSERT INTO candle_indicators (instrument_id, timeframe, ts, ao_value, donchian_upper,
                                           donchian_lower, donchian_mid, sl, sh, vix_value)
            SELECT instrument_id, timeframe, ts, %(ao_value)s, %(donchian_upper)s, %(donchian_lower)s,
                   %(donchian_mid)s, %(SL)s, %(SH)s, %(vix_value)s
            FROM c
            ON CONFLICT (instrument_id, timeframe, ts) DO UPDATE SET
                ao_value = EXCLUDED.ao_value, donchian_upper = EXCLUDED.donchian_upper,
                donchian_lower = EXCLUDED.donchian_lower, donchian_mid = EXCLUDED.donchian_mid,
                sl = EXCLUDED.sl, sh = EXCLUDED.sh, vix_value = EXCLUDED.vix_value""",
        pg_count_sql=f"SELECT count(*) FROM candles WHERE timeframe = '{timeframe}'",
        ts_col="timestamp",
        measure_col="close",
        pg_daily_sql=_daily(f"candles WHERE timeframe = '{timeframe}'", "ts", "close"),
    )


VIX_DATA = SourceTable(
    name="vix_data",
    pk="timestamp",
    select_sql="""
        SELECT timestamp, symbol, vix_value, vix_ao_value, vix_donchian_upper,
               vix_donchian_lower, vix_donchian_mid
        FROM vix_data ORDER BY timestamp""",
    upsert_sql="""
        INSERT INTO vix_observations (ts, instrument_id, value, ao_value, donchian_upper, donchian_lower, donchian_mid)
        VALUES (%(timestamp)s::timestamptz, (SELECT id FROM instruments WHERE symbol = %(symbol)s),
                %(vix_value)s, %(vix_ao_value)s, %(vix_donchian_upper)s, %(vix_donchian_lower)s, %(vix_donchian_mid)s)
        ON CONFLICT (ts) DO UPDATE SET
            instrument_id = EXCLUDED.instrument_id, value = EXCLUDED.value, ao_value = EXCLUDED.ao_value,
            donchian_upper = EXCLUDED.donchian_upper, donchian_lower = EXCLUDED.donchian_lower,
            donchian_mid = EXCLUDED.donchian_mid""",
    pg_count_sql="SELECT count(*) FROM vix_observations",
    ts_col="timestamp",
    measure_col="vix_value",
    pg_daily_sql=_daily("vix_observations", "ts", "value"),
)

SIGNALS = SourceTable(
    name="signals",
    pk="id",
    select_sql="SELECT id, timestamp, symbol, signal, reason, confidence_score FROM signals ORDER BY id",
    upsert_sql="""
        INSERT INTO signals (id, instrument_id, ts, signal, reason, confidence_score)
        VALUES (%(id)s, (SELECT id FROM instruments WHERE symbol = %(symbol)s), %(timestamp)s::timestamptz,
                %(signal)s, %(reason)s, %(confidence_score)s)
        ON CONFLICT (id) DO UPDATE SET
            instrument_id = EXCLUDED.instrument_id, ts = EXCLUDED.ts, signal = EXCLUDED.signal,
            reason = EXCLUDED.reason, confidence_score = EXCLUDED.confidence_score""",
    pg_count_sql="SELECT count(*) FROM signals",
    ts_col="timestamp",
    measure_col="confidence_score",
    pg_daily_sql=_daily("signals", "ts", "confidence_score"),
)

OPTION_DATA = SourceTable(
    name="option_data",
    pk="id",
    select_sql="""
        SELECT id, timestamp, symbol, strike_price, option_type, ltp, iv, expiry_date,
               spot_price, tradingsymbol, open_interest
        FROM option_data ORDER BY id""",
    # Header/line split + spot FD enforcement live in apply_option_data (migration 0004).
    upsert_sql="""
        SELECT apply_option_data(%(id)s::bigint, %(timestamp)s::text, %(symbol)s::text,
                                 %(strike_price)s::integer, %(option_type)s::text, %(ltp)s::float8,
                                 %(iv)s::float8, %(expiry_date)s::text, %(spot_price)s::numeric,
                                 %(tradingsymbol)s::text, %(open_interest)s::bigint)""",
    pg_count_sql="SELECT count(*) FROM option_snapshots",
    ts_col="timestamp",
    measure_col="ltp",
    pg_daily_sql=_daily("option_snapshots s JOIN option_chain_snapshots h ON h.id = s.chain_snapshot_id",
                        "h.ts", "s.ltp"),
)

DELTA_CACHE = SourceTable(
    name="delta_cache",
    pk="id",
    select_sql="""
        SELECT id, timestamp, symbol, strike_price, option_type, delta, expiry_date,
               spot_price, ltp, tradingsymbol
        FROM delta_cache ORDER BY id""",
    # Duplicate (contract, ts) rows: highest source id kept, others quarantined (see migration 0003).
    upsert_sql="""
        SELECT apply_delta_cache(%(id)s::bigint, %(timestamp)s::text, %(symbol)s::text, %(expiry_date)s::text,
                                 %(strike_price)s::integer, %(option_type)s::text, %(tradingsymbol)s::text,
                                 %(delta)s::float8, %(spot_price)s::numeric, %(ltp)s::float8)""",
    pg_count_sql="SELECT count(*) FROM delta_snapshots",
    ts_col="timestamp",
    measure_col="delta",
    pg_daily_sql=_daily("delta_snapshots", "ts", "delta"),
)

STRATEGY_STATE = SourceTable(
    name="dashboard_strategy_state",
    pk="strategy_id",
    select_sql="""
        SELECT strategy_id, display_name, status, mode, last_started_at, last_stopped_at, updated_at
        FROM dashboard_strategy_state ORDER BY strategy_id""",
    upsert_sql="""
        INSERT INTO dashboard_strategy_state (strategy_id, display_name, status, mode,
                                              last_started_at, last_stopped_at, updated_at)
        VALUES (%(strategy_id)s, %(display_name)s, %(status)s, %(mode)s, %(last_started_at)s::timestamptz,
                %(last_stopped_at)s::timestamptz, %(updated_at)s::timestamptz)
        ON CONFLICT (strategy_id) DO UPDATE SET
            display_name = EXCLUDED.display_name, status = EXCLUDED.status, mode = EXCLUDED.mode,
            last_started_at = EXCLUDED.last_started_at, last_stopped_at = EXCLUDED.last_stopped_at,
            updated_at = EXCLUDED.updated_at""",
    pg_count_sql="SELECT count(*) FROM dashboard_strategy_state",
    ts_col="updated_at",
    measure_col="NULL",  # no numeric column: count + timestamp range only
    pg_daily_sql=_daily("dashboard_strategy_state", "updated_at", "NULL::float8"),
)

TRADE_HISTORY = SourceTable(
    name="dashboard_trade_history",
    pk="id",
    select_sql="""
        SELECT id, strategy_id, symbol, entry_ts, exit_ts, side, qty, entry_price, exit_price,
               realized_pnl, status, source, position_type, section, subcat, exit_reason,
               sl_initial, sl_final, sl_adjustments
        FROM dashboard_trade_history ORDER BY id""",
    upsert_sql="""
        INSERT INTO dashboard_trade_history (
            id, strategy_id, instrument_id, contract_id, entry_ts, exit_ts, side, qty, entry_price,
            exit_price, realized_pnl, status, source, position_type, section, subcat, exit_reason,
            sl_initial, sl_final, sl_adjustments)
        SELECT %(id)s, %(strategy_id)s,
               COALESCE((SELECT id FROM instruments WHERE symbol = %(symbol)s), r.instrument_id),
               r.contract_id, %(entry_ts)s::timestamptz, %(exit_ts)s::timestamptz, %(side)s, %(qty)s,
               %(entry_price)s, %(exit_price)s, %(realized_pnl)s, %(status)s, %(source)s,
               %(position_type)s, %(section)s, %(subcat)s, %(exit_reason)s, %(sl_initial)s,
               %(sl_final)s, %(sl_adjustments)s
        FROM resolve_trade_contract(%(symbol)s) r
        ON CONFLICT (id) DO UPDATE SET
            strategy_id = EXCLUDED.strategy_id, instrument_id = EXCLUDED.instrument_id,
            contract_id = EXCLUDED.contract_id, entry_ts = EXCLUDED.entry_ts, exit_ts = EXCLUDED.exit_ts,
            side = EXCLUDED.side, qty = EXCLUDED.qty, entry_price = EXCLUDED.entry_price,
            exit_price = EXCLUDED.exit_price, realized_pnl = EXCLUDED.realized_pnl, status = EXCLUDED.status,
            source = EXCLUDED.source, position_type = EXCLUDED.position_type, section = EXCLUDED.section,
            subcat = EXCLUDED.subcat, exit_reason = EXCLUDED.exit_reason, sl_initial = EXCLUDED.sl_initial,
            sl_final = EXCLUDED.sl_final, sl_adjustments = EXCLUDED.sl_adjustments""",
    pg_count_sql="SELECT count(*) FROM dashboard_trade_history",
    ts_col="entry_ts",
    measure_col="realized_pnl",
    pg_daily_sql=_daily("dashboard_trade_history", "entry_ts", "realized_pnl"),
)

# Load order matters: observed contracts (option_data, delta_cache) before
# trades that may reference them; strategies before their trades (FK).
SOURCE_TABLES: dict[str, SourceTable] = {
    t.name: t for t in [*(_market_data(tf) for tf in ("1m", "5m", "15m", "1h")), VIX_DATA, SIGNALS,
                        OPTION_DATA, DELTA_CACHE, STRATEGY_STATE, TRADE_HISTORY]
}
