"""Shared helpers for end-to-end tests: real temp SQLite built by the bot's own
routines, real throwaway Postgres, and the cloudsync CLI run as a subprocess."""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:  # pragma: no cover
    pass

BOT_REPO = os.environ.get("BOT_REPO", r"C:\Users\aryan\Desktop\AlgoTrade")
if BOT_REPO not in sys.path:
    sys.path.append(BOT_REPO)


def make_tmpdir(testcase) -> Path:
    base = PROJECT_ROOT / ".test_tmp"
    base.mkdir(exist_ok=True)
    d = Path(tempfile.mkdtemp(dir=base))
    testcase.addCleanup(shutil.rmtree, d, True)
    return d


def make_bot_db(path: Path) -> Path:
    """Create an empty database with the bot's own table-creation routines."""
    from utils.db_setup import create_tables
    from server.dashboard_store import DashboardStore
    from datetime import datetime
    create_tables(str(path))
    # Creates dashboard_* tables and seeds 3 strategies + demo trade history,
    # exactly as the bot's dashboard server does on startup.
    DashboardStore(str(path)).initialize(reference_time=datetime(2026, 3, 27, 15, 0))
    # create_tables() predates two delta_cache columns that production gained
    # via ALTER TABLE (the bot's own tests hand-create them too). Apply the same
    # additive change so the fixture has production's column list.
    conn = sqlite3.connect(path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(delta_cache)")}
        for name, decl in (("ltp", "REAL"), ("tradingsymbol", "TEXT")):
            if name not in cols:
                conn.execute(f"ALTER TABLE delta_cache ADD COLUMN {name} {decl}")
        conn.commit()
    finally:
        conn.close()
    return path


def run_cli(*args, env=None, check=True) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    full_env.update(env or {})
    proc = subprocess.run(
        [sys.executable, "-m", "cloudsync", *map(str, args)],
        cwd=PROJECT_ROOT, env=full_env, capture_output=True, text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"cloudsync {args} failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    return proc


def sqlite_rows(path, sql, params=()):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def make_pg_database(testcase) -> str:
    """Create a throwaway Postgres database on the Docker server; dropped on cleanup."""
    import psycopg
    from psycopg import sql
    admin = os.environ["PG_ADMIN_DSN"]
    name = f"cs_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))

    def drop():
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
    testcase.addCleanup(drop)
    return psycopg.conninfo.make_conninfo(admin, dbname=name)


def pg_rows(dsn, query, params=None):
    import psycopg
    with psycopg.connect(dsn) as conn:
        return conn.execute(query, params).fetchall()
