"""Throwaway sandboxes for experiments: never run one on the main pair.

`create NAME` makes a matched pair:
  * <dir>/NAME/trading_bot.db : a copy of the main working copy (SQLite backup API,
    source opened read-only, so the copy is consistent even if the daemon runs);
  * Postgres database <main db>_sbx_NAME : a clone of the main cloud database
    (CREATE DATABASE ... TEMPLATE), so CDC state, sync_state and fingerprints match.
Experiments (bot write paths, chaos, benchmarks) then use the sandbox's sqlite
path and DSN; the main working copy and the main cloud database stay untouched.
`drop NAME` deletes both. Stop the sync daemon before creating a sandbox: the
template clone needs no other connections, and the pair is only consistent if
nothing syncs between the two copies.
"""
import re
import shutil
import sqlite3
from pathlib import Path

import psycopg
from psycopg import sql

from cloudsync.guard import assert_writable

_NAME = re.compile(r"^[a-z0-9_]{1,30}$")


def _names(name: str, from_dsn: str, directory: Path):
    if not _NAME.match(name):
        raise SystemExit("sandbox name: 1-30 characters of a-z, 0-9, _")
    main_db = psycopg.conninfo.conninfo_to_dict(from_dsn)["dbname"]
    box_dir = Path(directory) / name
    assert_writable(box_dir, "sandbox")
    return main_db, f"{main_db}_sbx_{name}", box_dir


def _admin(from_dsn: str) -> psycopg.Connection:
    return psycopg.connect(psycopg.conninfo.make_conninfo(from_dsn, dbname="postgres"), autocommit=True)


def create(name: str, from_sqlite: Path, from_dsn: str, directory: Path) -> dict:
    main_db, box_db, box_dir = _names(name, from_dsn, directory)
    if box_dir.exists():
        raise SystemExit(f"sandbox {name} already exists at {box_dir}: drop it first")
    box_dir.mkdir(parents=True)
    box_sqlite = box_dir / "trading_bot.db"
    src = sqlite3.connect(f"file:{Path(from_sqlite).resolve().as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(box_sqlite)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    with _admin(from_dsn) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(box_db), sql.Identifier(main_db)))
    return {"name": name, "sqlite": str(box_sqlite),
            "dsn": psycopg.conninfo.make_conninfo(from_dsn, dbname=box_db), "pg_database": box_db}


def drop(name: str, from_dsn: str, directory: Path) -> dict:
    _, box_db, box_dir = _names(name, from_dsn, directory)
    with _admin(from_dsn) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(box_db)))
    shutil.rmtree(box_dir, ignore_errors=True)
    return {"dropped": name, "pg_database": box_db}
