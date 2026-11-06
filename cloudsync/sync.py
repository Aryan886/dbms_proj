"""Sync engine: SQLite _changelog -> normalized Postgres, exactly-once in effect.

One pass:
  1. Drift check: each table's live column fingerprint is compared with the
     stored one; a mismatching table is paused (and logged), the rest go on.
  2. Prune changelog entries Postgres has already acknowledged (covers a crash
     between a commit and the prune that should have followed it).
  3. Batches of ~1000 entries after each active table's sync_state.last_seq:
       - the entries and the rows they point at are read in ONE SQLite read
         transaction (WAL: a consistent snapshot that never blocks the bot);
       - entries are collapsed per (table, pk): the row's CURRENT state is
         applied, so many updates become one upsert, and a missing row is a
         delete;
       - all deletes, upserts, rejects, the sync_state moves and the
         sync_batches row commit in ONE Postgres transaction;
       - only then are the entries pruned from SQLite.
A crash anywhere leaves Postgres fully before or fully after a batch, and a
replayed entry re-applies an idempotent upsert/delete: no duplicates, no gaps.
"""
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from cloudsync import pg
from cloudsync.apply import _ROW_ERRORS, _reject, apply_rows
from cloudsync.cdc import fingerprint, live_columns
from cloudsync.guard import assert_writable
from cloudsync.tables import SOURCE_TABLES

BATCH_SIZE = 1000
_SQLITE_PARAM_CHUNK = 500


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


# ---------- fault injection (tests and the day-3 chaos demo) ----------
# CLOUDSYNC_FAULT=<point>:<batch number>, point = mid_batch | after_commit.
# The process dies with os._exit (no cleanup, no commit), like a kill -9.
FAULT_EXIT_CODE = 75


def _fault(point: str, batch_no: int) -> None:
    spec = os.environ.get("CLOUDSYNC_FAULT", "")
    if spec and spec.split(":")[0] == point and int(spec.split(":")[1]) == batch_no:
        log(f"FAULT INJECTED: dying at {point} of batch {batch_no}")
        os._exit(FAULT_EXIT_CODE)


# ---------- SQLite side ----------
def _open_sqlite(sqlite_path: Path) -> sqlite3.Connection:
    assert_writable(sqlite_path, "sync (it prunes the changelog)")
    conn = sqlite3.connect(sqlite_path, isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _read_batch(lite, cursors: dict[str, int], active: list[str], batch_size: int):
    """Next entries for the active tables, and the current rows they point at."""
    if not active:
        return [], {}
    where = " OR ".join("(table_name = ? AND seq > ?)" for _ in active)
    params = [p for name in active for p in (name, cursors.get(name, 0))]
    lite.execute("BEGIN")  # one read snapshot for entries + rows
    try:
        entries = lite.execute(
            f"SELECT seq, table_name, pk, op, changed_at FROM _changelog WHERE {where} ORDER BY seq LIMIT ?",
            (*params, batch_size)).fetchall()
        pks = defaultdict(dict)  # table -> {pk: None}, insertion-ordered, deduplicated
        for e in entries:
            pks[e["table_name"]][e["pk"]] = None
        current = {}
        for name, keys in pks.items():
            table, keys = SOURCE_TABLES[name], list(keys)
            rows = {}
            for i in range(0, len(keys), _SQLITE_PARAM_CHUNK):
                chunk = keys[i:i + _SQLITE_PARAM_CHUNK]
                for r in lite.execute(table.select_by_pk_sql(len(chunk)), chunk):
                    rows[r[table.pk]] = dict(r)
            current[name] = (keys, rows)
    finally:
        lite.execute("COMMIT")
    return entries, current


def _prune(lite, cursors: dict[str, int]) -> int:
    pruned = 0
    for name, seq in cursors.items():
        pruned += lite.execute("DELETE FROM _changelog WHERE table_name = ? AND seq <= ?", (name, seq)).rowcount
    return pruned


# ---------- Postgres side ----------
def _apply_deletes(conn, table, pks) -> tuple[int, int]:
    """Same pattern as apply_rows: all at once (pipelined), row by row only if one fails."""
    if not pks:
        return 0, 0
    try:
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(table.delete_sql, [{"pk": pk} for pk in pks])
        return len(pks), 0
    except _ROW_ERRORS:
        pass
    deleted = rejected = 0
    with conn.cursor() as cur:
        for pk in pks:
            try:
                with conn.transaction():
                    cur.execute(table.delete_sql, {"pk": pk})
                deleted += 1
            except _ROW_ERRORS as err:  # e.g. FK: a strategy deleted while the cloud still has its trades
                _reject(cur, table, {table.pk: pk, "_op": "delete"}, err)
                rejected += 1
    return deleted, rejected


def _apply_batch(conn, entries, current, batch_no: int) -> dict:
    started = datetime.now(timezone.utc)
    upserts = deletes = rejected = 0
    with conn.transaction():
        # Rejects of the touched rows are re-decided from their current state.
        for name, (keys, _) in current.items():
            conn.execute("DELETE FROM rejected_rows WHERE source_table = %s AND source_pk = ANY(%s)",
                         (name, [str(k) for k in keys]))
        # Deletes in reverse load order (trades before their strategies), then
        # upserts in load order (contracts before the trades that use them).
        ordered = [n for n in SOURCE_TABLES if n in current]
        for name in reversed(ordered):
            table, (keys, rows) = SOURCE_TABLES[name], current[name]
            gone = keys if table.natural_key else [k for k in keys if k not in rows]
            _, r = _apply_deletes(conn, table, gone)
            deletes += len([k for k in keys if k not in rows])
            rejected += r
        for name in ordered:
            table, (keys, rows) = SOURCE_TABLES[name], current[name]
            present = [rows[k] for k in keys if k in rows]
            if present:
                a, r = apply_rows(conn, table, present)
                upserts += a
                rejected += r

        # Every change of the batch is applied but not committed yet.
        _fault("mid_batch", batch_no)
        last = defaultdict(int)
        for e in entries:
            last[e["table_name"]] = max(last[e["table_name"]], e["seq"])
        for name, seq in last.items():
            conn.execute("""INSERT INTO sync_state (source_table, last_seq, updated_at) VALUES (%s, %s, now())
                            ON CONFLICT (source_table) DO UPDATE SET last_seq = EXCLUDED.last_seq,
                                                                     updated_at = EXCLUDED.updated_at""",
                         (name, seq))
        oldest = min(datetime.fromisoformat(e["changed_at"]).replace(tzinfo=timezone.utc) for e in entries)
        conn.execute(
            """INSERT INTO sync_batches (first_seq, last_seq, entries, upserts, deletes, rejected, tables,
                                         started_at, committed_at, latency_ms, max_lag_ms)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp(),
                       extract(epoch FROM clock_timestamp() - %s) * 1000,
                       extract(epoch FROM clock_timestamp() - %s) * 1000)""",
            (entries[0]["seq"], entries[-1]["seq"], len(entries), upserts, deletes, rejected,
             sorted(last), started, started, oldest))
    return {"entries": len(entries), "upserts": upserts, "deletes": deletes, "rejected": rejected,
            "last_seq": dict(last)}


def _check_drift(lite, conn) -> list[str]:
    """Pause tables whose live columns no longer match the stored fingerprint."""
    stored = {name: (fp, status) for name, fp, status in
              conn.execute("SELECT source_table, fingerprint, status FROM schema_fingerprints")}
    missing = [n for n in SOURCE_TABLES if n not in stored]
    if missing:
        raise SystemExit(f"no stored fingerprint for {missing}: run `cloudsync cdc-install` first")
    active = []
    for name in SOURCE_TABLES:
        fp, status = stored[name]
        cols = live_columns(lite, name)
        if status == "active" and fingerprint(cols) != fp:
            version = conn.execute("SELECT coalesce(max(version), 0) FROM schema_version").fetchone()[0]
            conn.execute(
                """UPDATE schema_fingerprints SET status = 'paused', paused_at_version = %s, live_columns = %s,
                          live_fingerprint = %s, detected_at = now(), updated_at = now()
                   WHERE source_table = %s""", (version, Jsonb(cols), fingerprint(cols), name))
            conn.commit()
            log(f"SCHEMA DRIFT: {name} columns changed (fingerprint {fp} -> {fingerprint(cols)}); "
                f"table paused, other tables continue. Apply a migration, then `cloudsync drift-resume --table {name}`.")
            status = "paused"
        if status == "active":
            active.append(name)
    return active


def run_pass(sqlite_path: Path, conn: psycopg.Connection, batch_size: int = BATCH_SIZE) -> dict:
    """Sync everything currently in the changelog. Returns a summary."""
    lite = _open_sqlite(sqlite_path)
    try:
        active = _check_drift(lite, conn)
        cursors = {name: seq for name, seq in conn.execute("SELECT source_table, last_seq FROM sync_state")}
        conn.commit()
        _prune(lite, cursors)
        total = {"batches": 0, "entries": 0, "upserts": 0, "deletes": 0, "rejected": 0}
        while True:
            entries, current = _read_batch(lite, cursors, active, batch_size)
            if not entries:
                break
            total["batches"] += 1
            result = _apply_batch(conn, entries, current, total["batches"])
            _fault("after_commit", total["batches"])
            cursors.update(result.pop("last_seq"))
            _prune(lite, cursors)
            for k in ("entries", "upserts", "deletes", "rejected"):
                total[k] += result[k]
        total["paused_tables"] = [n for n in SOURCE_TABLES if n not in active]
        total["backlog"] = lite.execute("SELECT count(*) FROM _changelog").fetchone()[0]
        return total
    finally:
        lite.close()


# ---------- modes ----------
_RETRYABLE = (psycopg.OperationalError, sqlite3.OperationalError)


def once(sqlite_path: Path, dsn: str, batch_size: int, max_retries: int, backoff: float,
         backoff_cap: float) -> dict:
    """One deterministic pass; retries with exponential backoff while unreachable."""
    delay = backoff
    for attempt in range(max_retries + 1):
        try:
            with pg.connect(dsn, connect_timeout=5) as conn:
                return run_pass(sqlite_path, conn, batch_size)
        except _RETRYABLE as err:
            if attempt == max_retries:
                raise
            log(f"unavailable ({type(err).__name__}: {str(err).strip()[:120]}); retry {attempt + 1}/{max_retries} "
                f"in {delay:.1f}s")
            time.sleep(delay)
            delay = min(delay * 2, backoff_cap)


def daemon(sqlite_path: Path, dsn: str, batch_size: int, poll: float, backoff: float, backoff_cap: float) -> None:
    """Run forever: sync, sleep `poll` when idle, back off exponentially while offline."""
    delay = backoff
    log(f"sync daemon started: {sqlite_path} (batch {batch_size}, poll {poll}s)")
    while True:
        try:
            with pg.connect(dsn, connect_timeout=5) as conn:
                if delay != backoff:
                    log("connected again; resuming from sync_state")
                delay = backoff
                while True:
                    summary = run_pass(sqlite_path, conn, batch_size)
                    if summary["entries"]:
                        log(f"synced {summary['entries']} change(s) in {summary['batches']} batch(es): "
                            f"{summary['upserts']} upserts, {summary['deletes']} deletes, "
                            f"{summary['rejected']} rejected; backlog {summary['backlog']}")
                    else:
                        time.sleep(poll)
        except _RETRYABLE as err:
            log(f"unavailable ({type(err).__name__}: {str(err).strip()[:120]}); retrying in {delay:.1f}s")
            time.sleep(delay)
            delay = min(delay * 2, backoff_cap)
        except KeyboardInterrupt:
            log("sync daemon stopped")
            return


def drift_resume(sqlite_path: Path, dsn: str, table: str) -> dict:
    """Resume a paused table. Requires a migration applied since it was paused."""
    if table not in SOURCE_TABLES:
        raise SystemExit(f"unknown source table {table!r}")
    lite = _open_sqlite(sqlite_path)
    try:
        cols = live_columns(lite, table)
    finally:
        lite.close()
    with pg.connect(dsn) as conn:
        row = conn.execute("SELECT status, paused_at_version FROM schema_fingerprints WHERE source_table = %s",
                           (table,)).fetchone()
        if row is None or row[0] != "paused":
            raise SystemExit(f"{table} is not paused")
        version = conn.execute("SELECT coalesce(max(version), 0) FROM schema_version").fetchone()[0]
        if version <= row[1]:
            raise SystemExit(f"{table} was paused at schema version {row[1]} and the database is still at "
                             f"{version}: apply a migration for the drift first (`cloudsync migrate`)")
        conn.execute(
            """UPDATE schema_fingerprints SET status = 'active', columns = %s, fingerprint = %s,
                      paused_at_version = NULL, live_columns = NULL, live_fingerprint = NULL, updated_at = now()
               WHERE source_table = %s""", (Jsonb(cols), fingerprint(cols), table))
    log(f"{table} resumed at schema version {version} (fingerprint {fingerprint(cols)})")
    return {"table": table, "schema_version": version, "fingerprint": fingerprint(cols)}
