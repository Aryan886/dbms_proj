"""CDC installer: WAL mode, the _changelog table, generated triggers, fingerprints.

The only changes made to the bot's SQLite file are additive: the journal mode,
one table, one index and three triggers per in-scope table. The triggers are
generated from each table's LIVE column list (PRAGMA table_info), which gives
the primary-key column to record, so no trigger SQL is written by hand.

Each trigger records only (table, pk, op); the sync engine reads the row's
current state at apply time. That is what lets several updates to one row
collapse into a single upsert, and makes a replayed entry harmless.

Note on INSERT OR REPLACE (used by the bot for vix_data): SQLite does not fire
DELETE triggers for rows that REPLACE removes unless recursive_triggers is on.
That is safe here: the replacing row has the same pk (vix_data) or the same
natural key, so its INSERT entry re-applies the cloud row on that key.
"""
import hashlib
import json
import sqlite3
from pathlib import Path

from psycopg.types.json import Jsonb

from cloudsync import pg
from cloudsync.guard import assert_writable
from cloudsync.tables import SOURCE_TABLES, SourceTable

CHANGELOG_DDL = """
CREATE TABLE IF NOT EXISTS _changelog (
    -- AUTOINCREMENT: seq is never reused, even after the table is pruned empty.
    -- Without it SQLite would restart at max(rowid)+1 = 1 and new changes
    -- would sort below sync_state.last_seq and be skipped.
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name  TEXT NOT NULL,
    pk          NOT NULL,          -- no type affinity: integer ids stay integers
    op          TEXT NOT NULL CHECK (op IN ('I', 'U', 'D')),
    changed_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))  -- UTC
);
CREATE INDEX IF NOT EXISTS _changelog_table_seq ON _changelog (table_name, seq)
"""
_CHANGELOG_STATEMENTS = [s for s in CHANGELOG_DDL.split(";\n") if s.strip()]


def live_columns(conn: sqlite3.Connection, table: str) -> list[list]:
    """[name, declared type, pk position] in the table's physical column order."""
    return [[r[1], r[2], r[5]] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def fingerprint(columns: list[list]) -> str:
    return hashlib.sha256(json.dumps(columns).encode()).hexdigest()[:16]


def _pk_columns(columns: list[list]) -> tuple:
    """The live primary-key columns, in key order (PRAGMA table_info's pk position)."""
    return tuple(c[0] for c in sorted((c for c in columns if c[2]), key=lambda c: c[2]))


def _trigger_sql(table: SourceTable) -> list[str]:
    # A composite key (market_sma_1h) is recorded as one text value, the key
    # columns joined by '|'; SourceTable.key_sql builds the same expression.
    name, new, old = table.name, table.key_sql("NEW."), table.key_sql("OLD.")
    log = f"INSERT INTO _changelog (table_name, pk, op) VALUES ('{name}'"
    return [
        f'DROP TRIGGER IF EXISTS "_cdc_{name}_ins"',
        f'DROP TRIGGER IF EXISTS "_cdc_{name}_upd"',
        f'DROP TRIGGER IF EXISTS "_cdc_{name}_del"',
        f'CREATE TRIGGER "_cdc_{name}_ins" AFTER INSERT ON "{name}" BEGIN {log}, {new}, \'I\'); END',
        # A pk change is recorded under both keys: the old one resolves to a
        # delete, the new one to an upsert.
        f'CREATE TRIGGER "_cdc_{name}_upd" AFTER UPDATE ON "{name}" BEGIN {log}, {old}, \'U\'); '
        f"INSERT INTO _changelog (table_name, pk, op) SELECT '{name}', {new}, 'U' WHERE {new} IS NOT {old}; END",
        f'CREATE TRIGGER "_cdc_{name}_del" AFTER DELETE ON "{name}" BEGIN {log}, {old}, \'D\'); END',
    ]


def install(sqlite_path: Path, dsn: str) -> dict:
    assert_writable(sqlite_path, "cdc-install")
    conn = sqlite3.connect(sqlite_path, isolation_level=None, timeout=30)
    summary = {"tables": {}}
    try:
        summary["journal_mode"] = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        conn.execute("BEGIN IMMEDIATE")
        # (not executescript: it would COMMIT the open transaction first)
        for stmt in _CHANGELOG_STATEMENTS:
            conn.execute(stmt)
        fingerprints = {}
        for table in SOURCE_TABLES.values():
            cols = live_columns(conn, table.name)
            if not cols:
                raise SystemExit(f"source table {table.name} not found in {sqlite_path}")
            pk = _pk_columns(cols)
            if pk != table.key_columns:
                raise SystemExit(f"{table.name}: live primary key {list(pk)} differs from the mapped key "
                                 f"{list(table.key_columns)}")
            for stmt in _trigger_sql(table):
                conn.execute(stmt)
            fingerprints[table.name] = cols
            summary["tables"][table.name] = {"pk": "|".join(pk), "fingerprint": fingerprint(cols)}
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    # The stored fingerprint is the baseline the sync engine compares against.
    # Re-installing never overwrites it: that would silently accept drift.
    with pg.connect(dsn) as pconn:
        for name, cols in fingerprints.items():
            pconn.execute(
                """INSERT INTO schema_fingerprints (source_table, columns, fingerprint)
                   VALUES (%s, %s, %s) ON CONFLICT (source_table) DO NOTHING""",
                (name, Jsonb(cols), fingerprint(cols)))
    return summary
