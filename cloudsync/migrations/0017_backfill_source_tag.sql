-- The bot's dashboard seeds its own demo trades with source = 'backtest', so
-- that value can't tell backfilled rows apart (found on the main cloud: 92
-- "backtest" trades where 90 were backfilled). Backfilled rows get their own
-- tag; their negative ids stay the hard boundary.

ALTER TABLE dashboard_trade_history DROP CONSTRAINT dashboard_trade_history_backfill_tag;
UPDATE dashboard_trade_history SET source = 'backtest-backfill' WHERE id < 0;
ALTER TABLE dashboard_trade_history
    ADD CONSTRAINT dashboard_trade_history_backfill_tag CHECK ((id > 0) <> (source = 'backtest-backfill'));
