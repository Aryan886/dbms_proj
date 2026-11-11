"""The database side of the point-in-time-recovery demo (spec story 45).

RDS restores a whole instance, as a NEW instance, to any second inside its backup
window, by replaying the transaction log on top of the last snapshot. The restore
itself is done in the RDS console; this module provides the evidence around it:

  * `snapshot`   fingerprints one IST trading day: row count + md5 of the sorted
                 rows of every day-scoped base table, and the server clock;
  * `delete_day` deletes that day on purpose, in one transaction, and records the
                 server clock just before and after it (the restore target goes in
                 between the snapshot and `started_at`);
  * `verify`     recomputes the fingerprint on another database (the restored
                 instance) and says PASS only if every table is identical.

`delete_day` refuses the main cloud databases ($PG_DSN, $DOCKER_PG_DSN): the demo
runs on a sandbox database (D29). Fingerprints are computed with TimeZone = UTC so a
row's text form doesn't depend on the session.
"""
import json
import os
from datetime import date, timedelta
from pathlib import Path

import psycopg

def _in_day(ts: str) -> str:
    # A range on the raw column (index-friendly) covering one Asia/Kolkata day.
    return (f"{ts} >= (%(lo)s::timestamp AT TIME ZONE 'Asia/Kolkata') "
            f"AND {ts} < (%(hi)s::timestamp AT TIME ZONE 'Asia/Kolkata')")


# (table, predicate selecting the day's rows), children before parents so the
# delete respects FKs. option_snapshots has no ts of its own since the header/line
# split (migration 0004): its day is its header's. candle_indicators is deleted by
# its ON DELETE CASCADE from candles, but it is fingerprinted on its own so the
# restore is checked for it too.
DAY_TABLES = (
    ("option_snapshots",
     f"chain_snapshot_id IN (SELECT id FROM option_chain_snapshots WHERE {_in_day('ts')})"),
    ("option_chain_snapshots", _in_day("ts")),
    ("delta_snapshots", _in_day("ts")),
    ("candle_indicators", _in_day("ts")),
    ("candles", _in_day("ts")),
    ("candle_sma", _in_day("ts")),
    ("vix_observations", _in_day("ts")),
    ("signals", _in_day("ts")),
)
_CASCADED = {"candle_indicators"}


def _bounds(day: str):
    d = date.fromisoformat(day)
    return d.isoformat(), (d + timedelta(days=1)).isoformat()


def _connect(dsn: str) -> psycopg.Connection:
    conn = psycopg.connect(dsn)
    conn.execute("SET TimeZone = 'UTC'")
    return conn


def _fingerprint(conn, day: str) -> dict:
    lo, hi = _bounds(day)
    tables = {}
    for table, where in DAY_TABLES:
        rows, digest = conn.execute(
            f"SELECT count(*), md5(coalesce(string_agg(t::text, E'\\n' ORDER BY t::text), '')) "
            f"FROM {table} t WHERE {where}", {"lo": lo, "hi": hi}).fetchone()
        tables[table] = {"rows": rows, "md5": digest}
    return tables


def _server(conn) -> dict:
    now, db, host, version = conn.execute(
        "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), "
        "current_database(), coalesce(inet_server_addr()::text, 'local'), current_setting('server_version')"
    ).fetchone()
    return {"now": now, "database": db, "server_addr": host, "server_version": version}


def _write(out, record: dict) -> dict:
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def snapshot(dsn: str, day: str, out=None) -> dict:
    with _connect(dsn) as conn:
        srv = _server(conn)
        tables = _fingerprint(conn, day)
    return _write(out, {"day": day, "server_time": srv["now"], "database": srv["database"],
                        "server_version": srv["server_version"], "tables": tables})


def _same_database(a: str, b: str) -> bool:
    ca, cb = psycopg.conninfo.conninfo_to_dict(a), psycopg.conninfo.conninfo_to_dict(b)
    key = lambda c: ((c.get("host") or "localhost").lower(), str(c.get("port") or "5432"), c.get("dbname"))
    return key(ca) == key(cb)


def _refuse_main(dsn: str) -> None:
    for var in ("PG_DSN", "DOCKER_PG_DSN"):
        main = os.environ.get(var)
        if main and _same_database(dsn, main):
            raise SystemExit(f"REFUSED: pitr delete-day on the main cloud database (${var}). "
                             "Run it on a sandbox: cloudsync sandbox create NAME")


def delete_day(dsn: str, day: str, out=None) -> dict:
    _refuse_main(dsn)
    lo, hi = _bounds(day)
    deleted = {}
    with _connect(dsn) as conn:
        started = _server(conn)["now"]
        with conn.transaction():
            for table, where in DAY_TABLES:
                if table in _CASCADED:
                    deleted[table] = conn.execute(f"SELECT count(*) FROM {table} WHERE {where}",
                                                  {"lo": lo, "hi": hi}).fetchone()[0]
                    continue
                deleted[table] = conn.execute(f"DELETE FROM {table} WHERE {where}",
                                              {"lo": lo, "hi": hi}).rowcount
        srv = _server(conn)
    return _write(out, {"day": day, "database": srv["database"], "started_at": started,
                        "committed_at": srv["now"], "deleted": deleted})


def verify(dsn: str, snapshot_path, out=None) -> dict:
    expected = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    with _connect(dsn) as conn:
        srv = _server(conn)
        actual = _fingerprint(conn, expected["day"])
    tables = {}
    for name, exp in expected["tables"].items():
        got = actual.get(name, {"rows": None, "md5": None})
        tables[name] = {"expected_rows": exp["rows"], "rows": got["rows"],
                        "identical": got == exp}
    passed = all(t["identical"] for t in tables.values())
    return _write(out, {"day": expected["day"], "snapshot_time": expected["server_time"],
                        "database": srv["database"], "server_addr": srv["server_addr"],
                        "checked_at": srv["now"], "passed": passed, "tables": tables})


def format_verify(report: dict) -> str:
    lines = [f"pitr verify {report['day']} on {report['database']}: {'PASS' if report['passed'] else 'FAIL'}"]
    for name, t in report["tables"].items():
        mark = "identical" if t["identical"] else "DIFFERENT"
        lines.append(f"  {name:<24} {t['rows']!s:>8} rows (snapshot {t['expected_rows']})  {mark}")
    return "\n".join(lines)
