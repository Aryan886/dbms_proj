"""Runs the bot's UNCHANGED backtester on one SQLite file and writes its trades as JSON.

Started by cloudsync.parity in its own process (`python -I`, cwd = a scratch
directory), so the two runs being compared share no module state and any file
the bot writes relative to its working directory lands in scratch space.

usage: python -I _backtest_worker.py BOT_REPO DB_PATH START END OUT_JSON
"""
import dataclasses
import json
import sys
from datetime import datetime, time as dtime


def main() -> None:
    bot_repo, db_path, start, end, out = sys.argv[1:6]
    sys.path.append(bot_repo)
    from backtesting.backtest_bot import BacktestableBot
    from backtesting.runner import BacktestConfig, BacktestRunner

    # SHIM (decision D42, owner-approved): the bot's committed backtester crashes with
    # AttributeError whenever an open position is marked to market. NiftyBot's
    # mark-to-market log lines (bot commit 0e2b6b7) read self._last_options_snapshot_timestamp,
    # which BacktestableBot never sets. A class-level default fixes the lookup without
    # touching any bot file; the value only feeds a log line, and the same shim applies to
    # both runs being compared.
    shims = []
    if not hasattr(BacktestableBot, "_last_options_snapshot_timestamp"):
        BacktestableBot._last_options_snapshot_timestamp = None
        shims.append("BacktestableBot._last_options_snapshot_timestamp = None")

    config = BacktestConfig(start_date=datetime.combine(datetime.fromisoformat(start).date(), dtime(9, 15)),
                            end_date=datetime.combine(datetime.fromisoformat(end).date(), dtime(15, 30)),
                            db_path=db_path)
    result = BacktestRunner(config).run()
    payload = {"num_trades": result.num_trades, "total_pnl": result.total_pnl, "shims": shims,
               "trades": [dataclasses.asdict(t) for t in result.trades]}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, default=str)


if __name__ == "__main__":
    main()
