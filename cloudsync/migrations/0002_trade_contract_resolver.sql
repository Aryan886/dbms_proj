-- 0002: resolve a trade's tradingsymbol to an option_contracts row.
--
-- dashboard_trade_history stores option tradingsymbols, sometimes for
-- contracts never seen in option_data/delta_cache. Resolution order:
--   1. an existing contract with exactly this tradingsymbol;
--   2. parse the symbol and match/insert on the natural key
--      (instrument, expiry, strike, type):
--        weekly : NIFTY{YY}{M}{DD}{strike}{CE|PE}, M in 1-9,O,N,D (expiry in symbol)
--        monthly: NIFTY{YY}{MON}{strike}{CE|PE} (expiry day NOT in symbol ->
--                 last Tuesday of the month, last Thursday before Sep-2025,
--                 the NSE NIFTY expiry-day rule; holiday shifts are not modelled)
--      Contracts created here are flagged expiry_source = 'derived'.
--   3. otherwise NULLs (not an option symbol).
-- Returns the instrument too: a contract inserted here is not visible to other
-- subqueries of the calling statement (same snapshot).
CREATE FUNCTION resolve_trade_contract(p_symbol text, OUT contract_id integer, OUT instrument_id smallint)
LANGUAGE plpgsql AS $$
#variable_conflict use_column
DECLARE
    m          text[];
    v_inst     smallint;
    v_expiry   date;
    v_strike   integer;
    v_type     text;
    v_year     integer;
    v_month    integer;
    v_last_day date;
    v_dow      integer;
BEGIN
    SELECT oc.id, oc.instrument_id INTO contract_id, instrument_id
    FROM option_contracts oc WHERE oc.tradingsymbol = p_symbol;
    IF FOUND THEN
        RETURN;
    END IF;

    m := regexp_match(p_symbol, '^NIFTY(\d{2})([1-9OND])(\d{2})(\d{4,6})(CE|PE)$');
    IF m IS NOT NULL THEN
        v_year   := 2000 + m[1]::int;
        v_month  := strpos('123456789OND', m[2]);
        v_expiry := make_date(v_year, v_month, m[3]::int);
        v_strike := m[4]::int;
        v_type   := m[5];
    ELSE
        m := regexp_match(p_symbol,
            '^NIFTY(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{4,6})(CE|PE)$');
        IF m IS NULL THEN
            RETURN;
        END IF;
        v_year     := 2000 + m[1]::int;
        v_month    := array_position(ARRAY['JAN','FEB','MAR','APR','MAY','JUN',
                                           'JUL','AUG','SEP','OCT','NOV','DEC'], m[2]);
        v_last_day := (make_date(v_year, v_month, 1) + interval '1 month - 1 day')::date;
        v_dow      := CASE WHEN make_date(v_year, v_month, 1) >= DATE '2025-09-01' THEN 2 ELSE 4 END;
        v_expiry   := v_last_day - ((extract(dow FROM v_last_day)::int - v_dow + 7) % 7);
        v_strike   := m[3]::int;
        v_type     := m[4];
    END IF;

    SELECT id INTO v_inst FROM instruments WHERE symbol = 'NIFTY50';

    INSERT INTO option_contracts (instrument_id, expiry_date, strike, option_type, tradingsymbol, expiry_source)
    VALUES (v_inst, v_expiry, v_strike, v_type, p_symbol, 'derived')
    ON CONFLICT (instrument_id, expiry_date, strike, option_type) DO NOTHING;

    SELECT oc.id INTO contract_id FROM option_contracts oc
    WHERE oc.instrument_id = v_inst AND oc.expiry_date = v_expiry AND oc.strike = v_strike AND oc.option_type = v_type;
    instrument_id := v_inst;
END $$;
