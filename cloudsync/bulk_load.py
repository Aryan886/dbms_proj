"""One-time bulk load of the in-scope SQLite tables into the normalized schema."""
import sqlite3
from pathlib import Path

from cloudsync import pg
from cloudsync.apply import apply_rows
from cloudsync.tables import SOURCE_TABLES

BATCH_SIZE = 5000


def _read_rows(sqlite_path: Path, select_sql: str):
    conn = sqlite3.connect(f"file:{Path(sqlite_path).resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(select_sql)
        while batch := cur.fetchmany(BATCH_SIZE):
            yield [dict(r) for r in batch]
    finally:
        conn.close()


def run(sqlite_path: Path, dsn: str, only: list[str] | None = None) -> dict:
    """Load every in-scope table, or only the ones named (e.g. a table added by a later migration)."""
    unknown = set(only or []) - set(SOURCE_TABLES)
    if unknown:
        raise SystemExit(f"unknown source table(s): {sorted(unknown)}")
    summary = {}
    with pg.connect(dsn) as conn:
        for table in SOURCE_TABLES.values():
            if only and table.name not in only:
                continue
            read = 0
            for batch in _read_rows(sqlite_path, table.select_sql):
                with conn.transaction():
                    apply_rows(conn, table, batch)
                read += len(batch)
            # Count from rejected_rows: some rejections (e.g. delta_cache
            # duplicates) are decided inside SQL functions, not by apply_rows.
            rejected = conn.execute("SELECT count(*) FROM rejected_rows WHERE source_table = %s",
                                    (table.name,)).fetchone()[0]
            summary[table.name] = {"read": read, "kept": read - rejected, "rejected": rejected}
    return summary
