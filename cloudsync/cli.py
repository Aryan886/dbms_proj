import argparse
import json
import os
from pathlib import Path

from cloudsync import bench, bulk_load, cdc, migrate, prep, reconcile, replay, sandbox, sync

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(PROJECT_ROOT / ".env")  # never overrides variables already set


def main(argv=None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(prog="cloudsync")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prep", help="Make a working copy of the bot DB and record VACUUM stats")
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--workdir", required=True, type=Path)

    m = sub.add_parser("migrate", help="Apply pending numbered Postgres migrations")
    m.add_argument("--extra-dir", type=Path, action="append", default=[],
                   help="Additional directory of NNNN_name.sql migrations (e.g. a drift fix)")
    _add_dsn(m)

    b = sub.add_parser("bulk-load", help="One-time load of the in-scope SQLite tables into Postgres")
    b.add_argument("--sqlite", required=True, type=Path)
    b.add_argument("--tables", default="", help="comma-separated subset of source tables (default: all)")
    _add_dsn(b)

    r = sub.add_parser("reconcile", help="Compare SQLite and Postgres; write a report")
    r.add_argument("--sqlite", required=True, type=Path)
    r.add_argument("--levels", default="1,2", help="Comma-separated levels to run, e.g. 1,2,3")
    r.add_argument("--out", required=True, type=Path, help="Directory for the report files")
    r.add_argument("--start", default=None, help="level 3: first backtest day (YYYY-MM-DD)")
    r.add_argument("--end", default=None, help="level 3: last backtest day (YYYY-MM-DD)")
    r.add_argument("--parity-dir", type=Path, default=None,
                   help="level 3: keep the export, the source copy and both backtest logs here")
    _add_dsn(r)

    c = sub.add_parser("cdc-install", help="WAL mode + _changelog + generated triggers + fingerprints")
    c.add_argument("--sqlite", required=True, type=Path)
    _add_dsn(c)

    s = sub.add_parser("sync", help="Apply captured changes to Postgres")
    s.add_argument("mode", choices=["once", "daemon"])
    s.add_argument("--sqlite", required=True, type=Path)
    s.add_argument("--batch-size", type=int, default=sync.BATCH_SIZE)
    s.add_argument("--poll", type=float, default=1.0, help="daemon: idle sleep in seconds")
    s.add_argument("--max-retries", type=int, default=3, help="once: connection retries before giving up")
    s.add_argument("--backoff", type=float, default=0.5, help="first retry delay (doubles each time)")
    s.add_argument("--backoff-cap", type=float, default=30.0)
    _add_dsn(s)

    d = sub.add_parser("drift-resume", help="Resume a table paused by schema drift (after a migration)")
    d.add_argument("--sqlite", required=True, type=Path)
    d.add_argument("--table", required=True)
    _add_dsn(d)

    w = sub.add_parser("bench-wal", help="Benchmark concurrent write+read: rollback journal vs WAL")
    w.add_argument("--sqlite", required=True, type=Path, help="Database to copy (never modified)")
    w.add_argument("--out", required=True, type=Path)
    w.add_argument("--seconds", type=float, default=10.0)
    w.add_argument("--timeout", type=float, default=5.0, help="busy timeout (Python sqlite3 default: 5 s)")
    w.add_argument("--table", default="delta_cache", help="table the reader scans")

    x = sub.add_parser("sandbox", help="Throwaway copy of the working copy + cloud DB for experiments")
    x.add_argument("action", choices=["create", "drop"])
    x.add_argument("name")
    x.add_argument("--from-sqlite", type=Path, default=Path("data/trading_bot.db"))
    x.add_argument("--from-dsn", default=None, help="main cloud DSN to clone (default: $PG_DSN)")
    x.add_argument("--dir", type=Path, default=Path("data/sandboxes"))

    y = sub.add_parser("replay", help="Replay a historical day into a CDC'd sandbox (stand-in for the Kite feed)")
    y.add_argument("--source", required=True, type=Path, help="Database to read the day from (opened read-only)")
    y.add_argument("--target", required=True, type=Path, help="Sandbox SQLite with CDC installed")
    y.add_argument("--day", required=True, help="YYYY-MM-DD")
    y.add_argument("--speed", type=float, default=0.0, help="simulated seconds per real second (0 = no pacing)")
    y.add_argument("--chaos", default="", help="comma-separated: revise, rebuild, kill")
    y.add_argument("--sync-dsn", default=None, help="run `sync once` against this DSN during the replay")
    y.add_argument("--sync-every", type=int, default=0, help="replay steps between sync runs")

    f = sub.add_parser("backfill-trades",
                       help="Run the backtester on a copy and put its trades in the cloud's trade history (tagged)")
    f.add_argument("--sqlite", required=True, type=Path, help="Database the backtest reads (copied, never modified)")
    f.add_argument("--start", required=True, help="first backtest day (YYYY-MM-DD)")
    f.add_argument("--end", required=True, help="last backtest day (YYYY-MM-DD)")
    f.add_argument("--strategy", default="nifty-options")
    f.add_argument("--out", type=Path, default=None, help="directory for the summary and the trade list")
    f.add_argument("--work-dir", type=Path, default=None, help="scratch directory (default: a temp dir)")
    _add_dsn(f)

    i = sub.add_parser("bench-indexes", help="EXPLAIN ANALYZE the bot's query shapes under index variants")
    i.add_argument("--out", required=True, type=Path)
    _add_dsn(i)

    t = sub.add_parser("pitr", help="Point-in-time-recovery demo: fingerprint, delete and verify one IST day")
    t.add_argument("action", choices=["snapshot", "delete-day", "verify"])
    t.add_argument("--day", help="YYYY-MM-DD (snapshot, delete-day)")
    t.add_argument("--snapshot", type=Path, help="fingerprint written by `pitr snapshot` (verify)")
    t.add_argument("--out", type=Path, default=None, help="JSON record of this step")
    _add_dsn(t)

    args = parser.parse_args(argv)
    if args.command == "pitr":
        from cloudsync import pitr
        if args.action == "verify":
            if not args.snapshot:
                raise SystemExit("pitr verify needs --snapshot")
            report = pitr.verify(_dsn(args), args.snapshot, args.out)
            print(pitr.format_verify(report))
            return 0 if report["passed"] else 1
        if not args.day:
            raise SystemExit(f"pitr {args.action} needs --day")
        step = pitr.snapshot if args.action == "snapshot" else pitr.delete_day
        print(json.dumps(step(_dsn(args), args.day, args.out), indent=2))
        return 0
    if args.command == "prep":
        print(json.dumps(prep.run(args.source, args.workdir), indent=2))
    elif args.command == "migrate":
        applied = migrate.run(_dsn(args), args.extra_dir)
        print(f"applied {len(applied)} migration(s): {applied}")
    elif args.command == "bulk-load":
        only = [t.strip() for t in args.tables.split(",") if t.strip()] or None
        print(json.dumps(bulk_load.run(args.sqlite, _dsn(args), only), indent=2))
    elif args.command == "cdc-install":
        print(json.dumps(cdc.install(args.sqlite, _dsn(args)), indent=2))
    elif args.command == "sync" and args.mode == "once":
        print(json.dumps(sync.once(args.sqlite, _dsn(args), args.batch_size, args.max_retries,
                                   args.backoff, args.backoff_cap), indent=2))
    elif args.command == "sync":
        sync.daemon(args.sqlite, _dsn(args), args.batch_size, args.poll, args.backoff, args.backoff_cap)
    elif args.command == "drift-resume":
        print(json.dumps(sync.drift_resume(args.sqlite, _dsn(args), args.table), indent=2))
    elif args.command == "bench-wal":
        print(json.dumps(bench.run(args.sqlite, args.out, args.seconds, args.timeout, args.table), indent=2))
    elif args.command == "sandbox":
        dsn = args.from_dsn or _dsn(argparse.Namespace(dsn=None))
        if args.action == "create":
            print(json.dumps(sandbox.create(args.name, args.from_sqlite, dsn, args.dir), indent=2))
        else:
            print(json.dumps(sandbox.drop(args.name, dsn, args.dir), indent=2))
    elif args.command == "replay":
        chaos = {c.strip() for c in args.chaos.split(",") if c.strip()}
        print(json.dumps(replay.run(args.source, args.target, args.day, args.speed, chaos, args.sync_dsn,
                                    args.sync_every), indent=2))
    elif args.command == "backfill-trades":
        from cloudsync import backfill
        bot_repo = os.environ.get("BOT_REPO", r"C:\Users\aryan\Desktop\AlgoTrade")
        print(json.dumps(backfill.backfill(args.sqlite, _dsn(args), args.start, args.end, bot_repo, args.strategy,
                                           args.out, args.work_dir), indent=2))
    elif args.command == "bench-indexes":
        from cloudsync import index_audit
        results = index_audit.run(_dsn(args), args.out)
        print(f"index audit: {len(results['variants'])} variants -> {args.out}")
    elif args.command == "reconcile":
        levels = [int(x) for x in args.levels.split(",") if x.strip()]
        report = reconcile.run(args.sqlite, _dsn(args), levels, args.out, args.start, args.end, args.parity_dir)
        print(f"reconciliation {'PASSED' if report['passed'] else 'FAILED'} -> {args.out}")
        return 0 if report["passed"] else 1
    return 0


def _add_dsn(parser):
    parser.add_argument("--dsn", default=None, help="Postgres DSN (default: $PG_DSN)")


def _dsn(args) -> str:
    dsn = args.dsn or os.environ.get("PG_DSN")
    if not dsn:
        raise SystemExit("No Postgres DSN: pass --dsn or set PG_DSN in .env")
    return dsn
