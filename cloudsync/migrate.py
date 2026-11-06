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


def available(extra_dirs=()) -> list[tuple[int, str, Path]]:
    found = {}
    for directory in (MIGRATIONS_DIR, *map(Path, extra_dirs)):
        for path in directory.glob("*.sql"):
            m = _NAME.match(path.name)
            if m:
                version = int(m.group(1))
                if version in found:
                    raise SystemExit(f"duplicate migration version {version}: {found[version][2]} and {path}")
                found[version] = (version, m.group(2), path)
    return [found[v] for v in sorted(found)]


def run(dsn: str, extra_dirs=()) -> list[int]:
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
        for version, name, path in available(extra_dirs):
            if version in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_version (version, name) VALUES (%s, %s)", (version, name))
            applied_now.append(version)
    return applied_now
