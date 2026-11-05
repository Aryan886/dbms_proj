"""Numbered SQL migrations, tracked in schema_version.

Files live in cloudsync/migrations as NNNN_name.sql. Each pending migration
runs in its own transaction together with its schema_version row, so a
failed migration leaves no partial schema behind.
"""
import re
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME = re.compile(r"^(\d{4})_(.+)\.sql$")


def available() -> list[tuple[int, str, Path]]:
    found = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = _NAME.match(path.name)
        if m:
            found.append((int(m.group(1)), m.group(2), path))
    return found


def run(dsn: str) -> list[int]:
    applied_now = []
    with psycopg.connect(dsn) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version     integer PRIMARY KEY,
                name        text NOT NULL,
                applied_at  timestamptz NOT NULL DEFAULT now()
            )""")
        conn.commit()
        done = {v for (v,) in conn.execute("SELECT version FROM schema_version")}
        for version, name, path in available():
            if version in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_version (version, name) VALUES (%s, %s)", (version, name))
            applied_now.append(version)
    return applied_now
