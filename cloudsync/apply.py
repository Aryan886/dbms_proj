"""Apply source rows to Postgres, quarantining rows the database rejects.

Shared by the bulk loader and (day 2) the sync engine. Constraints are
enforced by Postgres, not re-implemented here: a batch is first applied as a
whole; if any row violates a constraint the batch is rolled back and replayed
row by row under savepoints, and each failing row is written to rejected_rows
with the constraint name Postgres reported. Nothing is silently dropped.
"""
import json

import psycopg
from psycopg.types.json import Jsonb

from cloudsync.tables import SourceTable

# Row-level failures that mean "this row is bad", as opposed to infrastructure
# failures (connection lost, etc.), which must propagate.
_ROW_ERRORS = (psycopg.errors.IntegrityError, psycopg.errors.DataError)


def _reject(cur, table: SourceTable, row: dict, err: psycopg.Error) -> None:
    diag = err.diag
    constraint = diag.constraint_name or (diag.sqlstate and psycopg.errors.lookup(diag.sqlstate).__name__) or "unknown"
    cur.execute(
        """INSERT INTO rejected_rows (source_table, source_pk, raw_row, violated_constraint, detail)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (source_table, source_pk) DO UPDATE SET
               raw_row = EXCLUDED.raw_row, violated_constraint = EXCLUDED.violated_constraint,
               detail = EXCLUDED.detail, rejected_at = now()""",
        (table.name, str(row[table.pk]), Jsonb(json.loads(json.dumps(row, default=str))),
         constraint, diag.message_primary),
    )


def apply_rows(conn: psycopg.Connection, table: SourceTable, rows: list[dict]) -> tuple[int, int]:
    """Upsert `rows` inside the caller's transaction. Returns (applied, rejected)."""
    try:
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(table.upsert_sql, rows)
        return len(rows), 0
    except _ROW_ERRORS:
        pass  # savepoint rolled back; find the offending rows one at a time

    applied = rejected = 0
    with conn.cursor() as cur:
        for row in rows:
            try:
                with conn.transaction():
                    cur.execute(table.upsert_sql, row)
                applied += 1
            except _ROW_ERRORS as err:
                _reject(cur, table, row, err)
                rejected += 1
    return applied, rejected
