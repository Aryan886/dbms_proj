import argparse
import json
import os
from pathlib import Path

from cloudsync import bulk_load, migrate, prep, reconcile


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cloudsync")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prep", help="Make a working copy of the bot DB and record VACUUM stats")
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--workdir", required=True, type=Path)

    m = sub.add_parser("migrate", help="Apply pending numbered Postgres migrations")
    _add_dsn(m)

    b = sub.add_parser("bulk-load", help="One-time load of the in-scope SQLite tables into Postgres")
    b.add_argument("--sqlite", required=True, type=Path)
    _add_dsn(b)

    r = sub.add_parser("reconcile", help="Compare SQLite and Postgres; write a report")
    r.add_argument("--sqlite", required=True, type=Path)
    r.add_argument("--levels", default="1,2", help="Comma-separated levels to run, e.g. 1,2")
    r.add_argument("--out", required=True, type=Path, help="Directory for the report files")
    _add_dsn(r)

    args = parser.parse_args(argv)
    if args.command == "prep":
        print(json.dumps(prep.run(args.source, args.workdir), indent=2))
    elif args.command == "migrate":
        applied = migrate.run(_dsn(args))
        print(f"applied {len(applied)} migration(s): {applied}")
    elif args.command == "bulk-load":
        print(json.dumps(bulk_load.run(args.sqlite, _dsn(args)), indent=2))
    elif args.command == "reconcile":
        levels = [int(x) for x in args.levels.split(",") if x.strip()]
        report = reconcile.run(args.sqlite, _dsn(args), levels, args.out)
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
